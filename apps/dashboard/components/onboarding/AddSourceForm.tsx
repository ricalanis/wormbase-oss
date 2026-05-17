"use client";

import { useState } from "react";
import { Input, Select, Button } from "@wormbase/design";
import { Receipt } from "../../lib/receipts";

const KIND_OPTS = [
  { value: "table", label: "Table" },
  { value: "view", label: "View" },
  { value: "api", label: "API" },
  { value: "file", label: "File / drop" },
];

const CLASS_OPTS = [
  { value: "internal", label: "Internal" },
  { value: "public", label: "Public" },
  { value: "restricted", label: "Restricted" },
  { value: "pii", label: "PII" },
];

export function AddSourceForm() {
  const [uri, setUri] = useState("");
  const [kind, setKind] = useState("table");
  const [owner, setOwner] = useState("");
  const [cls, setCls] = useState("internal");
  const [receipt, setReceipt] = useState<{
    hash: string;
    source: string;
    owner: string;
    classification: string;
  } | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!uri.trim() || !owner.trim()) return;
    const res = await fetch("/api/sources/propose", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ uri, owner, classification: cls, kind }),
    });
    const json = await res.json();
    setReceipt(json.receipt);
  }

  return (
    <form
      data-testid="add-source-form"
      onSubmit={submit}
      style={{ display: "flex", flexDirection: "column", gap: 14, maxWidth: 540 }}
    >
      <Input
        label="URI"
        value={uri}
        onChange={(e) => setUri(e.currentTarget.value)}
        placeholder="snowflake://analytics.subscriptions"
        data-testid="add-source-uri"
      />
      <Select
        label="Kind"
        options={KIND_OPTS}
        value={kind}
        onChange={(e) => setKind(e.currentTarget.value)}
        data-testid="add-source-kind"
      />
      <Input
        label="Owner"
        value={owner}
        onChange={(e) => setOwner(e.currentTarget.value)}
        placeholder="ricardo-bot"
        data-testid="add-source-owner"
      />
      <Select
        label="Classification default"
        options={CLASS_OPTS}
        value={cls}
        onChange={(e) => setCls(e.currentTarget.value)}
        data-testid="add-source-class"
      />
      <Button type="submit" data-testid="add-source-submit">
        Propose source
      </Button>
      {receipt ? (
        <Receipt
          hash={receipt.hash}
          source={receipt.source}
          owner={receipt.owner}
          classification={receipt.classification}
        />
      ) : null}
    </form>
  );
}
