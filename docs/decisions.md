# Decisiones de workflow e iteración

> Decisiones de proceso, no de arquitectura.
> Para decisiones técnicas/arquitectónicas del producto, ver `ARCHITECTURE.md` o ADRs en `architecture/`.

## Cómo usar este archivo

Documenta una decisión cuando elijas un modo de trabajo que afectará futuras sesiones (cuándo usar Plan mode, qué requiere verificación manual, cómo se commitea, etc.).

Formato por entrada:

```
### YYYY-MM-DD — <título corto de la decisión>

**Decisión:** Qué se decidió, en una frase.
**Contexto:** Qué problema o trade-off motivó la decisión.
**Consecuencias:** Qué cambia en cómo trabajamos a partir de ahora.
**Revisar si:** Condición bajo la cual reconsiderar esta decisión.
```

---

### 2026-05-20 — Adopción del workflow plan → verify → reflect

**Decisión:** Toda tarea no trivial sigue el ciclo del CLAUDE.md global: planear (Plan mode) → implementar en pasos pequeños → verificar (tests/lint/run) → registrar aprendizajes en `changelog.md` y `known_issues.md`.
**Contexto:** Las sesiones largas sin trazabilidad pierden el compounding knowledge y repiten errores.
**Consecuencias:** `changelog.md`, `known_issues.md` y este archivo se actualizan al final de cada tarea significativa. `DELIVERY_LOG.md` queda como registro formal de releases, separado del registro de sesiones.
**Revisar si:** El overhead de mantener los tres archivos supera el valor que aportan, o si surge un mecanismo mejor de trazabilidad.
