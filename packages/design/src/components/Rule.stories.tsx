import { Rule } from "./Rule";

export default { title: "Atoms / Rule" };

export const AllVariants = () => (
  <div style={{ display: "grid", gap: 24, padding: 24, width: 480 }}>
    <Caption label="thin — paper-edge / section divider">
      <Rule variant="thin" />
    </Caption>
    <Caption label="strong — 1px ink / primary boundary">
      <Rule variant="strong" />
    </Caption>
    <Caption label="double — 3px double ink / Royal Society heading">
      <Rule variant="double" />
    </Caption>
    <Caption label="dashed — provisional / pending ledger">
      <Rule variant="dashed" />
    </Caption>
  </div>
);

function Caption({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {children}
      <span
        className="wb-mono"
        style={{
          fontSize: 10,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          color: "var(--wb-color-hash-gray)",
        }}
      >
        {label}
      </span>
    </div>
  );
}
