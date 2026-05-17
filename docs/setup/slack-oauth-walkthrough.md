# Slack OAuth — Setup walkthrough (5 minutos)

Esta guía cierra los 3 items Tier-1 que el `what is missing` audit
identificó como bloqueadores para el demo en vivo. Después de
seguirla, el botón "Connect to Slack" en `/onboarding` funciona
contra cualquier workspace que admin-ees.

**Pre-requisito:** ya tienes una Slack app en api.slack.com con
`SLACK_BOT_TOKEN_BASEWORM` funcionando (es la app que usa la sim para
postear como personas). Si no, créala primero con
`docs/slack-sim-manifest.json`.

---

## Step 1 — Levantar el túnel HTTPS (1 min)

Slack OAuth requiere un Redirect URL HTTPS. Cloudflared sidecar te da
uno gratis:

```bash
make tunnel
```

Espera ~5 segundos. Output esperado:

```
WORMBASE_DASHBOARD_URL=https://fifth-talent-permitted-affecting.trycloudflare.com
Tunnel ready. Restart dashboard: make dashboard-restart
```

**Copia esa URL** — la vas a usar en Step 3 y Step 4.

> ⚠️ **Importante:** la URL rota en cada `make tunnel`. Si reinicias
> el túnel, hay que volver a hacer Step 3 con la URL nueva.

```bash
make dashboard-restart
```

---

## Step 2 — Copiar Client ID + Client Secret (2 min)

1. Abre <https://api.slack.com/apps>
2. Click en tu app (la que tiene `wormbase` o `WormBase` en el nombre)
3. En la sidebar izquierda → **Basic Information**
4. Scroll a **App Credentials**
5. **Client ID:** click "Show" → copia el valor (formato: `<digits>.<digits>`)
6. **Client Secret:** click "Show" → copia el valor (formato: hex string)

7. En tu repo, edita `.env`:

```env
SLACK_CLIENT_ID=1234567890.1234567890123
SLACK_CLIENT_SECRET=abcdef1234567890abcdef1234567890
WORMBASE_DASHBOARD_URL=https://fifth-talent-permitted-affecting.trycloudflare.com
```

> Las dos primeras keys NO van a git. `.env` ya está en `.gitignore`.
> Si por accidente hacen commit, rota el secret en api.slack.com →
> Basic Information → "Regenerate".

---

## Step 3 — Registrar el Redirect URL en la Slack app (1 min)

1. En tu Slack app → **OAuth & Permissions** (sidebar izquierda)
2. Scroll a **Redirect URLs**
3. Click **Add New Redirect URL**
4. Pega:

```
https://fifth-talent-permitted-affecting.trycloudflare.com/onboarding/oauth/slack/callback
```

(reemplaza el subdominio con el tunnel URL de Step 1, sin slash final)

5. Click **Add**, luego **Save URLs**

> Si el túnel rota mañana, vuelve aquí y agrega la URL nueva. Slack
> permite múltiples Redirect URLs registrados al mismo tiempo, así
> que no tienes que borrar la vieja.

---

## Step 4 — (Opcional) Distribution Public (1 min)

**Si solo demuestras en BaseWorm:** salta este paso. La app ya
funciona porque tú admin-eas el workspace.

**Si quieres demostrar en otro workspace** (un cliente, una pantalla
compartida que no es tuya):

1. En tu Slack app → **Manage Distribution** (sidebar izquierda)
2. Scroll a **Public Distribution**
3. Click **Activate Public Distribution**
4. Slack te pide aceptar términos. Hazlo.

> ⚠️ Distribution = Public es **irreversible** una vez aprobada. Si
> tu app es solo para demos internas, mejor déjala restricted.

---

## Step 5 — Reiniciar el dashboard + verificar (1 min)

```bash
make dashboard-restart
make doctor
```

Output esperado:

```
== .env ==
  [ok]     SLACK_CLIENT_ID set
  [ok]     SLACK_CLIENT_SECRET set
  [ok]     WORMBASE_DASHBOARD_URL set
  ...
```

Abre el dashboard en el túnel:

```
https://fifth-talent-permitted-affecting.trycloudflare.com/onboarding
```

Click **Connect to Slack**. Te debe redirigir a slack.com → workspace
picker → "Authorize" → callback a tu dashboard → `/onboarding/welcome`
con el cascade SSE en vivo.

Si todo funciona, **estás listo para el demo en vivo**.

---

## Troubleshooting

### `oauth_callback_failed` — Slack rechaza el redirect

- Verifica que el Redirect URL registrado en Slack coincide
  EXACTAMENTE con el del `.env` (incluyendo trailing slash o no, https
  no http, sin port suffix).
- El túnel pudo haber rotado entre Step 3 y Step 5.

### "App not installed in this workspace"

- Click "Add to Slack" desde la página de tu app (api.slack.com).
- El bot user tiene que estar en el workspace antes de que el OAuth
  flow funcione.

### Cloudflared 502/503 desde Slack

- El túnel está vivo pero no rutea. `make dashboard-restart` y
  espera 30s.
- Verifica que `dashboard` container está healthy: `make doctor`.

### Distribution restricted bloquea workspaces ajenos

- Slack restringe instalación a workspaces que tú admin-eas.
- Si necesitas demostrar en otro: o (a) Distribution Public, o (b) el
  cliente crea su propia Slack app y reusa los manifests.

---

## Para producción (post-demo)

Cuando el producto pase a customers reales:

- **Custom domain con Cloudflare Tunnel.** Migra del trycloudflare
  free tunnel a un named tunnel con tu dominio (ej. `wormbase.example.com`).
  Esto te da una URL estable que no rota.
- **Multiple environments.** Una app Slack por env (dev/staging/prod);
  las secrets en una bóveda real, no en `.env`.
- **App Directory.** Para distribución masiva, somete a Slack App
  Directory review (~2-4 semanas de proceso).

Para todos esos pasos, abre un issue en el repositorio del proyecto.
