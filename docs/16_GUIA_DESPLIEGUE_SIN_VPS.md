# SPORTPREDICT AI — GUÍA DE DESPLIEGUE EN LA NUBE SIN VPS ($0 USD)

**Código de Documento:** `16_GUIA_DESPLIEGUE_SIN_VPS.md`  
**Objetivo:** Publicar la aplicación completa a producción en plataformas administradas (Serverless / PaaS) sin necesidad de alquilar ni administrar un servidor Linux/VPS.

---

## Arquitectura Serverless / PaaS Recomendada ($0 USD de costo inicial)

```
                    ┌───────────────────────────────┐
                    │       Usuarios / Navegador    │
                    └───────────────┬───────────────┘
                                    │
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │             Frontend: VERCEL (Plan Gratuito)           │
       │    - Next.js 15 Standalone / CDN Global Ultrarrápido   │
       │    - Despliegue automático con cada push a GitHub      │
       └──────────────┬──────────────────────────┬──────────────┘
                      │                          │
        (Llamadas API)│             (Login / JWT)│
                      ▼                          ▼
┌───────────────────────────────┐   ┌───────────────────────────────┐
│  Backend: RENDER o RAILWAY   │   │  Base de Datos y Autenticación│
│    (FastAPI + ML Calibrado)   │   │     SUPABASE (Plan Gratuito)  │
│ - Corre Dockerfile optimizado │   │ - PostgreSQL 16 Administrado  │
│ - Valida JWT de Supabase      │◄──┤ - Supabase Auth (Email + Pass)│
│ - Healthchecks /health,/ready │   │ - Triggers de Inmutabilidad   │
└───────────────┬───────────────┘   └───────────────────────────────┘
                │
                │ (Cron cada 6 horas)
                ▼
┌───────────────────────────────────────────────┐
│  Automatización Fase 5: GITHUB ACTIONS o CRON │
│  - Descarga partidos de fuentes gratuitas CC0 │
│  - Registra predicciones pre-kickoff con SHA  │
│  - Liquida automáticamente partidos al cerrar │
└───────────────────────────────────────────────┘
```

---

## Paso 1: Subir tu código a GitHub

1. Crea un repositorio privado o público en tu cuenta de [GitHub](https://github.com/new) (ej. `sportpredict-ai`).
2. Sube el código desde tu terminal:
   ```bash
   git remote add origin https://github.com/TU_USUARIO/sportpredict-ai.git
   git push -u origin main
   ```

---

## Paso 2: Crear el Proyecto en Supabase (Gratis)

1. Entra a [supabase.com](https://supabase.com) y crea una cuenta gratuita.
2. Crea un nuevo proyecto (ej. `sportpredict-prod`) y guarda la contraseña de base de datos que asignes.
3. En **Project Settings $\rightarrow$ Database**:
   - Copia la **Connection String (URI)** en modo `Session` o `Transaction`.
   - La URL tendrá esta forma:  
     `postgresql+psycopg://postgres:[TU_PASSWORD]@db.[PROJECT_REF].supabase.co:5432/postgres`
4. En **Project Settings $\rightarrow$ API**:
   - Copia **Project URL** (`https://[PROJECT_REF].supabase.co`).
   - Copia **anon public key** (`eyJhbGci...`).
   - Copia **JWT Secret** (en la pestaña API Settings).

---

## Paso 3: Desplegar el Backend en Render o Railway

### Opción A: Render (Recomendada, usa el archivo `render.yaml`)

1. Regístrate en [render.com](https://render.com).
2. Haz clic en **New $\rightarrow$ Blueprint**.
3. Conecta tu repositorio de GitHub `sportpredict-ai`.
4. Render detectará automáticamente el archivo [`render.yaml`](file:///f:/Proyectos/Predicciones/render.yaml) y creará:
   - **Web Service:** `sportpredict-backend`
   - **Cron Job:** `sportpredict-fase5-scheduler`
5. En las variables de entorno del servicio, completa:
   - `DATABASE_URL`: tu conexión de Supabase.
   - `SUPABASE_URL`: tu URL de Supabase.
   - `SUPABASE_ANON_KEY`: tu anon key.
   - `SUPABASE_JWT_SECRET`: tu JWT secret.
   - `ADMIN_EMAILS`: tu correo electrónico para tener permisos de administrador.
   - `CORS_ORIGINS`: la URL donde vivirá tu frontend (ej. `https://sportpredict.vercel.app`).
6. Haz clic en **Apply**. Render compilará el Dockerfile y levantará el backend. Te dará una URL pública como:  
   `https://sportpredict-backend.onrender.com`

---

## Paso 4: Desplegar el Frontend en Vercel (Gratis)

1. Entra a [vercel.com](https://vercel.com) e inicia sesión con tu cuenta de GitHub.
2. Haz clic en **Add New $\rightarrow$ Project** e importa `sportpredict-ai`.
3. Vercel detectará el archivo [`vercel.json`](file:///f:/Proyectos/Predicciones/vercel.json) y seleccionará automáticamente el directorio raíz `frontend`.
4. En **Environment Variables**, agrega:
   - `NEXT_PUBLIC_API_URL`: la URL de tu backend en Render (ej. `https://sportpredict-backend.onrender.com`).
   - `NEXT_PUBLIC_SUPABASE_URL`: tu URL de Supabase.
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`: tu anon key de Supabase.
5. Haz clic en **Deploy**.
6. En menos de 2 minutos tu frontend estará publicado en una URL con HTTPS gratuito (ej. `https://sportpredict-ai.vercel.app`).

*Nota:* Vuelve a Render y asegúrate de que `CORS_ORIGINS` tenga exactamente la URL de tu frontend en Vercel.

---

## Paso 5: Automatización Diaria de Fase 5 (Totalmente Gratis)

Ya no necesitas tener un servidor encendido para ejecutar las predicciones y liquidaciones diarias:

1. El archivo [`.github/workflows/fase5-cron.yml`](file:///f:/Proyectos/Predicciones/.github/workflows/fase5-cron.yml) ejecutará el ciclo de Fase 5 automáticamente 3 veces al día usando GitHub Actions.
2. En tu repositorio de GitHub, ve a **Settings $\rightarrow$ Secrets and variables $\rightarrow$ Actions** y agrega:
   - `BACKEND_API_URL`: `https://sportpredict-backend.onrender.com`
   - `SUPABASE_SERVICE_ROLE_KEY`: tu clave `service_role` de Supabase.

¡Listo! Cada 8 horas GitHub Actions llamará a tu backend para descargar partidos, sellar pronósticos antes del inicio y liquidar los resultados finalizados de forma completamente desatendida.
