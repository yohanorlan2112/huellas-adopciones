"""API 2 – Adopciones. Dueña de la tabla `adopciones`; consume API 1 por HTTP/REST."""
import os
from datetime import datetime, timezone
from typing import Literal, Optional
from uuid import UUID

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from supabase import create_client

load_dotenv()
db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
MASCOTAS_URL = os.environ["MASCOTAS_API_URL"].rstrip("/")
T = "adopciones"

app = FastAPI(
    title="API Adopciones – Huellas de Esperanza",
    description="Solicitudes de adopción. Verifica disponibilidad y actualiza estados en la API de Mascotas.",
    version="1.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class SolicitudIn(BaseModel):
    mascota_id: UUID
    solicitante_nombre: str = Field(min_length=2, max_length=120)
    solicitante_email: EmailStr
    solicitante_telefono: Optional[str] = None
    motivo: str = Field(min_length=10, description="Por qué quiere adoptar")


class SolicitudOut(BaseModel):
    id: UUID
    mascota_id: UUID
    mascota_nombre: Optional[str] = None
    solicitante_nombre: str
    solicitante_email: str
    solicitante_telefono: Optional[str] = None
    motivo: str
    estado: Literal["pendiente", "aprobada", "rechazada"]
    creado_en: datetime
    resuelto_en: Optional[datetime] = None


def llamar_mascotas(method: str, path: str) -> httpx.Response:
    try:
        with httpx.Client(timeout=15) as c:
            return c.request(method, f"{MASCOTAS_URL}{path}")
    except httpx.HTTPError:
        raise HTTPException(503, "API de Mascotas no disponible")


def get_solicitud(sid: UUID) -> dict:
    r = db.table(T).select("*").eq("id", str(sid)).execute().data
    if not r:
        raise HTTPException(404, "Solicitud no encontrada")
    return r[0]


@app.get("/health", tags=["Sistema"])
def health():
    mascotas = llamar_mascotas("GET", "/health")
    return {"status": "ok", "service": "adopciones", "mascotas_api": mascotas.status_code == 200}


@app.post("/adopciones", response_model=SolicitudOut, status_code=201, tags=["Adopciones"])
def crear(s: SolicitudIn):
    """Registra una solicitud. Consulta a API 1: la mascota debe existir y estar disponible."""
    r = llamar_mascotas("GET", f"/mascotas/{s.mascota_id}")
    if r.status_code == 404:
        raise HTTPException(404, "La mascota no existe")
    if r.status_code != 200:
        raise HTTPException(502, "Respuesta inesperada de API de Mascotas")
    mascota = r.json()
    if mascota["estado"] != "disponible":
        raise HTTPException(409, "La mascota ya no está disponible")
    data = s.model_dump(mode="json") | {"mascota_nombre": mascota["nombre"]}
    return db.table(T).insert(data).execute().data[0]


@app.get("/adopciones", response_model=list[SolicitudOut], tags=["Adopciones"])
def listar(estado: Optional[Literal["pendiente", "aprobada", "rechazada"]] = None,
           mascota_id: Optional[UUID] = None):
    q = db.table(T).select("*").order("creado_en", desc=True)
    if estado:
        q = q.eq("estado", estado)
    if mascota_id:
        q = q.eq("mascota_id", str(mascota_id))
    return q.execute().data


@app.get("/adopciones/{sid}", response_model=SolicitudOut, tags=["Adopciones"])
def obtener(sid: UUID):
    return get_solicitud(sid)


@app.post("/adopciones/{sid}/aprobar", response_model=SolicitudOut, tags=["Adopciones"])
def aprobar(sid: UUID):
    """
    1) Pide a API 1 marcar la mascota como adoptada (UPDATE atómico → 409 si ya lo está).
    2) Guarda la solicitud como aprobada (índice único parcial = 2ª barrera).
    3) Si el paso 2 falla, compensa liberando la mascota.
    4) Rechaza automáticamente las demás solicitudes pendientes de esa mascota.
    """
    sol = get_solicitud(sid)
    if sol["estado"] != "pendiente":
        raise HTTPException(409, f"La solicitud ya está '{sol['estado']}'")

    r = llamar_mascotas("POST", f"/mascotas/{sol['mascota_id']}/marcar-adoptada")
    if r.status_code == 409:
        raise HTTPException(409, "La mascota ya tiene una adopción aprobada")
    if r.status_code == 404:
        raise HTTPException(404, "La mascota ya no existe")
    if r.status_code != 200:
        raise HTTPException(502, "No se pudo actualizar la mascota")

    ahora = datetime.now(timezone.utc).isoformat()
    try:
        res = (db.table(T).update({"estado": "aprobada", "resuelto_en": ahora})
               .eq("id", str(sid)).eq("estado", "pendiente").execute().data)
        if not res:
            raise RuntimeError("estado cambió")
    except Exception:
        llamar_mascotas("POST", f"/mascotas/{sol['mascota_id']}/liberar")  # compensación
        raise HTTPException(409, "No se pudo aprobar la solicitud; se revirtió el estado de la mascota")

    (db.table(T).update({"estado": "rechazada", "resuelto_en": ahora})
     .eq("mascota_id", sol["mascota_id"]).eq("estado", "pendiente").execute())
    return res[0]


@app.post("/adopciones/{sid}/rechazar", response_model=SolicitudOut, tags=["Adopciones"])
def rechazar(sid: UUID):
    sol = get_solicitud(sid)
    if sol["estado"] != "pendiente":
        raise HTTPException(409, f"La solicitud ya está '{sol['estado']}'")
    ahora = datetime.now(timezone.utc).isoformat()
    return (db.table(T).update({"estado": "rechazada", "resuelto_en": ahora})
            .eq("id", str(sid)).execute().data[0])
