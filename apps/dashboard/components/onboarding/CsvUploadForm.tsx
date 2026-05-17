"use client";
/**
 * CsvUploadForm — multipart CSV upload UI (Block G3 / PRD §17).
 *
 * Two-phase form:
 *   1. IdentityForm — name + email + position + org_size.
 *   2. File picker — single CSV; size capped to 25 MB at the route handler.
 *
 * Submits multipart/form-data to /api/onboarding/upload. On success the
 * server returns { redirect: "/onboarding/whats-next" } and we navigate.
 */
import { useRef, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import { IdentityForm, type IdentitySubmitArgs } from "./IdentityForm";

const MAX_BYTES = 25 * 1024 * 1024;

export function CsvUploadForm() {
  const router = useRouter();
  const [phase, setPhase] = useState<"identity" | "file" | "submitting">(
    "identity",
  );
  const [identity, setIdentity] = useState<IdentitySubmitArgs | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function onIdentitySubmitted(args: IdentitySubmitArgs) {
    setIdentity(args);
    setPhase("file");
  }

  async function onUpload(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!identity) return;
    if (!file) {
      setError("Pick a CSV file");
      return;
    }
    if (file.size > MAX_BYTES) {
      setError(
        `File is ${(file.size / 1024 / 1024).toFixed(1)} MB; cap is 25 MB`,
      );
      return;
    }

    setPhase("submitting");
    try {
      const fd = new FormData();
      fd.append("file", file);
      fd.append("identity", JSON.stringify(identity));
      const res = await fetch("/api/onboarding/upload", {
        method: "POST",
        body: fd,
      });
      const text = await res.text();
      let body: { redirect?: string; error?: string };
      try {
        body = JSON.parse(text);
      } catch {
        throw new Error(`server returned non-JSON: ${text.slice(0, 200)}`);
      }
      if (!res.ok) {
        throw new Error(body.error || `upload failed (${res.status})`);
      }
      router.push(body.redirect || "/onboarding/whats-next");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setPhase("file");
    }
  }

  if (phase === "identity") {
    return (
      <IdentityForm
        connectorKind="csv_local"
        connectorLabel="CSV upload"
        onSubmitted={onIdentitySubmitted}
      />
    );
  }

  return (
    <form
      data-testid="csv-upload-form"
      onSubmit={onUpload}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 14,
        border: "1px solid var(--wb-color-paper-edge)",
        background: "var(--wb-color-paper)",
        padding: 20,
      }}
    >
      <header style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <span
          className="wb-mono"
          style={{
            fontSize: 10,
            letterSpacing: "0.18em",
            textTransform: "uppercase",
            color: "var(--wb-color-hash-gray)",
          }}
        >
          upload your data
        </span>
        <h3
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontSize: 20,
            fontWeight: 500,
          }}
        >
          Pick a CSV
        </h3>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--wb-font-serif)",
            fontStyle: "italic",
            color: "var(--wb-color-aged-ink-soft)",
            fontSize: 13,
            lineHeight: 1.5,
          }}
        >
          25 MB cap. The worm profiles every column on landing — types,
          nullables, distinct counts, PII hints — and proposes a first KPI
          within seconds.
        </p>
      </header>

      <input
        ref={inputRef}
        data-testid="csv-upload-file-input"
        type="file"
        accept=".csv,text/csv"
        required
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        style={{
          fontFamily: "var(--wb-font-mono)",
          fontSize: 13,
          padding: 8,
          border: "1px dashed var(--wb-color-paper-edge)",
          background: "var(--wb-color-paper-deep)",
          borderRadius: 0,
        }}
      />

      {file ? (
        <div
          data-testid="csv-upload-file-meta"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-aged-ink-soft)",
          }}
        >
          {file.name} · {(file.size / 1024).toFixed(1)} KB
        </div>
      ) : null}

      {error ? (
        <div
          data-testid="csv-upload-error"
          className="wb-mono"
          style={{
            fontSize: 11,
            color: "var(--wb-color-sepia-warning-deep)",
            border: "1px solid var(--wb-color-sepia-warning-deep)",
            background: "var(--wb-color-sepia-warning-soft)",
            padding: "8px 12px",
          }}
        >
          {error}
        </div>
      ) : null}

      <button
        type="submit"
        data-testid="csv-upload-submit"
        disabled={phase === "submitting"}
        className="wb-mono"
        style={{
          fontSize: 12,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "10px 16px",
          border: "1px solid var(--wb-color-aged-ink)",
          background:
            phase === "submitting"
              ? "var(--wb-color-paper-deep)"
              : "var(--wb-color-botanical-green-soft)",
          color: "var(--wb-color-aged-ink)",
          cursor: phase === "submitting" ? "wait" : "pointer",
          borderRadius: 0,
          alignSelf: "flex-start",
        }}
      >
        {phase === "submitting" ? "uploading…" : "upload & cascade"}
      </button>
    </form>
  );
}
