-- Ejecutar en Supabase > SQL Editor
create extension if not exists "pgcrypto";

create table if not exists mascotas (
  id uuid primary key default gen_random_uuid(),
  nombre text not null,
  especie text not null check (especie in ('perro','gato','otro')),
  raza text,
  edad_meses int not null check (edad_meses >= 0),
  descripcion text,
  foto_url text,
  estado text not null default 'disponible' check (estado in ('disponible','adoptada')),
  creado_en timestamptz not null default now()
);

create table if not exists adopciones (
  id uuid primary key default gen_random_uuid(),
  mascota_id uuid not null,            -- referencia lógica a API 1 (sin FK: servicios independientes)
  mascota_nombre text,                 -- copia informativa
  solicitante_nombre text not null,
  solicitante_email text not null,
  solicitante_telefono text,
  motivo text not null,
  estado text not null default 'pendiente' check (estado in ('pendiente','aprobada','rechazada')),
  creado_en timestamptz not null default now(),
  resuelto_en timestamptz
);

-- Regla de negocio reforzada en BD: una mascota solo puede tener UNA adopción aprobada
create unique index if not exists uq_una_aprobada_por_mascota
  on adopciones (mascota_id) where estado = 'aprobada';

-- Datos de ejemplo
insert into mascotas (nombre, especie, raza, edad_meses, descripcion) values
 ('Luna','perro','Criollo',18,'Juguetona y sociable con niños.'),
 ('Miel','gato','Mestizo',8,'Tranquila, ideal para apartamento.'),
 ('Rocco','perro','Labrador',36,'Activo, necesita espacio para correr.');
