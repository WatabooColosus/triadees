# Tríade Ω — cuentas protegidas en Colab

## Estado y modelo

El frontend React del puerto 8010 es sólo una interfaz: la API FastAPI debe
proteger las rutas con bearer sessions en el backend. En producción la
autenticación es obligatoria por defecto; `TRIADE_LOCAL_NO_AUTH` es exclusiva
del entorno aislado de pruebas.

Autenticación propia implementada con FastAPI, SQLite, Argon2, tokens aleatorios
revocables y expirables. No es un servicio de correo: para demostrar posesión de
una dirección externa se necesita un servidor SMTP real con TLS. Se rechaza el
registro cuando SMTP no está configurado; **jamás se devuelve el código de
verificación por API**. Un servidor Mailpit sirve para pruebas, no verifica
direcciones externas reales.

## Primera cuenta (sin SMTP)

En **la consola confiable de Colab**, tras instalar el código y arrancar una
sola vez el servidor, ejecuta:

```python
import getpass
from pathlib import Path
from tools.bootstrap_owner_account import bootstrap

db = Path("/content/Triade/triade/memory/triade.db")
correo = input("Correo del propietario: ").strip()
clave = getpass.getpass("Contraseña (12+ caracteres): ")
confirmacion = getpass.getpass("Confirma contraseña: ")
assert clave == confirmacion, "Las contraseñas no coinciden"
print(bootstrap(db, correo, clave))
del clave, confirmacion
```

- Sólo permite un propietario cuando `auth_users` está totalmente vacío.
- Crea el registro con `admin` y `verified_at` sólo desde una consola ya
  autenticada del operador, no desde una petición pública.
- Si el registro web falló por `smtp_not_configured`, el código nuevo no crea
  ninguna fila y el bootstrap puede proceder.
- Si ya hay usuarios, **se rechaza el bootstrap**; no borres la base para
  saltar ese control.
- Guarda respaldos cifrados de la nueva base: Colab puede perder disco al
  reiniciar. No incluyas claves ni tokens en la copia pública.

## Registro público de otras personas

Configura en memoria de Colab o en secretos privados del despliegue estas
variables (no escribas valores secretos en celdas compartidas ni GitHub):

```text
TRIADE_SMTP_HOST=<proveedor SMTP>
TRIADE_SMTP_PORT=587
TRIADE_SMTP_FROM=<remitente autorizado>
TRIADE_SMTP_USER=<usuario del proveedor>
TRIADE_SMTP_PASSWORD=<secreto de la cuenta SMTP>
TRIADE_PUBLIC_BASE_URL=https://<host público real de Tríade>
```

Puerto 465 también está soportado con TLS implícito. Para otros puertos
se exige STARTTLS y validación del certificado; no hay envío sin cifrar.
Si `TRIADE_PUBLIC_BASE_URL` no está definido como HTTPS, el mensaje contiene
un **código de un solo uso** para pegar en «Verificar correo» del panel,
no un enlace local incorrecto.

En Colab, establece el secreto con `google.colab.userdata.get`, nunca
hardcodeando credenciales en el cuaderno, y pásalo al **proceso servidor**
como variable de entorno. Si cambias las variables de correo en una celda,
debes reiniciar ordenadamente la API para que las herede.

`GET /api/auth/registration-status` devuelve sólo disponibilidad y motivo,
nunca host, usuario, contraseña ni el código.

## Política de seguridad

- Registro de terceros: rol `viewer`; no se habilitan automáticamente
  funciones de operador ni de administrador.
- Código: 256 bits aleatorios, sólo SHA256 en SQLite, expiración 15 minutos,
  se inutiliza al verificar.
- Contraseñas: Argon2; mínimo 12 caracteres y longitud acotada.
- Registro: cuota local por dirección normalizada y cliente de red. La IP
  se transforma en digest antes de registrarla en la auditoría.
- Fallo SMTP: no queda usuario parcialmente creado; la API no divulga
  credenciales ni respuestas internas del servidor de correo.
- Sesiones: tokens opacos aleatorios, expiración y revocación. La aplicación
  actualmente almacena el bearer en `sessionStorage`; migrar a cookies
  `HttpOnly` con protección CSRF antes de una exposición amplia es una
  mejora de seguridad pendiente, no una capacidad ya demostrada.
- Seguridad adicional antes de abrir registro al público: límites perimetrales,
  TLS HTTPS extremo a extremo, CSP, copias de seguridad de la base, rotación
  de secretos, prevención de bots, y reglas de autorización por acción.

## Diagnóstico local sin credenciales

```python
import json, sqlite3, urllib.request
from pathlib import Path

print(
    json.loads(
        urllib.request.urlopen(
            "http://127.0.0.1:8010/api/auth/registration-status",
            timeout=5,
        ).read()
    )
)
db = Path("/content/Triade/triade/memory/triade.db")
with sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True) as conn:
    print("SQLite:", conn.execute("PRAGMA integrity_check").fetchone()[0])
    for table in (
        "auth_users",
        "auth_email_identities",
        "auth_sessions",
        "worker_runs",
        "runtime_health_snapshots",
    ):
        print(table, conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
```

Nunca imprimas `password_hash`, `token_hash`, `verification_hash`,
la contraseña SMTP ni los valores de API keys. Esta lectura comprueba tablas
y registros; no certifica por sí misma el trabajo vivo de workers, Ollama o
la continuidad de un proceso cuya URL externa ha cambiado.
