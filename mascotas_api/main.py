"""API 1 – Mascotas. Dueña de la tabla `mascotas` y de su disponibilidad."""
import os
from typing import Literal, Optional
from uuid import UUID

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from supabase import create_client

load_dotenv()
db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
T = "mascotas"

app = FastAPI(
    title="API Mascotas – Huellas de Esperanza",
    description="Registro, consulta y disponibilidad de mascotas para adopción.",
    version="1.0.0",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class MascotaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    especie: Literal["perro", "gato", "otro"]
    raza: Optional[str] = None
    edad_meses: int = Field(ge=0, le=360)
    descripcion: Optional[str] = None
    foto_url: Optional[str] = None


class MascotaOut(MascotaIn):
    id: UUID
    estado: Literal["disponible", "adoptada"]


@app.get("/health", tags=["Sistema"])
def health():
    return {"status": "ok", "service": "mascotas"}


@app.post("/mascotas", response_model=MascotaOut, status_code=201, tags=["Mascotas"])
def crear(m: MascotaIn):
    """Registra una mascota (queda `disponible`)."""
    return db.table(T).insert(m.model_dump()).execute().data[0]


@app.get("/mascotas", response_model=list[MascotaOut], tags=["Mascotas"])
def listar(estado: Optional[Literal["disponible", "adoptada"]] = None,
           especie: Optional[Literal["perro", "gato", "otro"]] = None,
           limit: int = Query(100, le=500)):
    q = db.table(T).select("*").order("creado_en", desc=True).limit(limit)
    if estado:
        q = q.eq("estado", estado)
    if especie:
        q = q.eq("especie", especie)
    return q.execute().data


@app.get("/mascotas/{mascota_id}", response_model=MascotaOut, tags=["Mascotas"])
def obtener(mascota_id: UUID):
    r = db.table(T).select("*").eq("id", str(mascota_id)).execute().data
    if not r:
        raise HTTPException(404, "Mascota no encontrada")
    return r[0]


@app.put("/mascotas/{mascota_id}", response_model=MascotaOut, tags=["Mascotas"])
def actualizar(mascota_id: UUID, m: MascotaIn):
    r = db.table(T).update(m.model_dump()).eq("id", str(mascota_id)).execute().data
    if not r:
        raise HTTPException(404, "Mascota no encontrada")
    return r[0]


@app.delete("/mascotas/{mascota_id}", status_code=204, tags=["Mascotas"])
def eliminar(mascota_id: UUID):
    db.table(T).delete().eq("id", str(mascota_id)).execute()


# ---- Endpoints de integración (los consume API 2) ----
def _cambiar_estado(mascota_id: UUID, desde: str, hacia: str):
    """UPDATE condicional atómico: solo cambia si el estado actual es `desde`."""
    r = (db.table(T).update({"estado": hacia})
         .eq("id", str(mascota_id)).eq("estado", desde).execute().data)
    if r:
        return r[0]
    existe = db.table(T).select("estado").eq("id", str(mascota_id)).execute().data
    if not existe:
        raise HTTPException(404, "Mascota no encontrada")
    raise HTTPException(409, f"La mascota está '{existe[0]['estado']}', se esperaba '{desde}'")


@app.post("/mascotas/{mascota_id}/marcar-adoptada", response_model=MascotaOut, tags=["Integración"])
def marcar_adoptada(mascota_id: UUID):
    """disponible → adoptada. Devuelve 409 si ya fue adoptada (evita doble adopción)."""
    return _cambiar_estado(mascota_id, "disponible", "adoptada")


@app.post("/mascotas/{mascota_id}/liberar", response_model=MascotaOut, tags=["Integración"])
def liberar(mascota_id: UUID):
    """adoptada → disponible (compensación si falla el registro de la adopción)."""
    return _cambiar_estado(mascota_id, "adoptada", "disponible")
