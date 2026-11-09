"""Pruebas de integración end-to-end contra las APIs en ejecución.
Uso:  MASCOTAS_URL=https://... ADOPCIONES_URL=https://... pytest -v tests/
"""
import os
import httpx
import pytest

M = os.getenv("MASCOTAS_URL", "http://localhost:8001").rstrip("/")
A = os.getenv("ADOPCIONES_URL", "http://localhost:8002").rstrip("/")
c = httpx.Client(timeout=30)

SOL = {"solicitante_nombre": "Ana Prueba", "solicitante_email": "ana@test.com",
       "motivo": "Tengo casa con patio y experiencia con perros."}


@pytest.fixture()
def mascota():
    r = c.post(f"{M}/mascotas", json={"nombre": "TestPet", "especie": "perro", "edad_meses": 12})
    assert r.status_code == 201
    yield r.json()
    c.delete(f"{M}/mascotas/{r.json()['id']}")


def solicitar(mid, nombre="Ana Prueba"):
    return c.post(f"{A}/adopciones", json={**SOL, "solicitante_nombre": nombre, "mascota_id": mid})


def test_health_integrado():
    assert c.get(f"{A}/health").json()["mascotas_api"] is True


def test_solicitud_mascota_inexistente():
    assert solicitar("00000000-0000-0000-0000-000000000000").status_code == 404


def test_flujo_completo_aprobacion(mascota):
    s = solicitar(mascota["id"])
    assert s.status_code == 201 and s.json()["estado"] == "pendiente"
    ap = c.post(f"{A}/adopciones/{s.json()['id']}/aprobar")
    assert ap.status_code == 200 and ap.json()["estado"] == "aprobada"
    assert c.get(f"{M}/mascotas/{mascota['id']}").json()["estado"] == "adoptada"
    assert solicitar(mascota["id"]).status_code == 409


def test_no_doble_aprobacion(mascota):
    s1 = solicitar(mascota["id"], "Uno").json()
    s2 = solicitar(mascota["id"], "Dos").json()
    assert c.post(f"{A}/adopciones/{s1['id']}/aprobar").status_code == 200
    assert c.get(f"{A}/adopciones/{s2['id']}").json()["estado"] == "rechazada"
    assert c.post(f"{A}/adopciones/{s2['id']}/aprobar").status_code == 409


def test_rechazo_deja_mascota_disponible(mascota):
    s = solicitar(mascota["id"]).json()
    assert c.post(f"{A}/adopciones/{s['id']}/rechazar").json()["estado"] == "rechazada"
    assert c.get(f"{M}/mascotas/{mascota['id']}").json()["estado"] == "disponible"
