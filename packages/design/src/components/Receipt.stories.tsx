import "../styles.css";
import { Receipt } from "./Receipt";

export const Full = () => (
  <div style={{ maxWidth: 520 }}>
    <Receipt
      hash="a3f9c2"
      source="subscriptions × accounts"
      owner="ricardo"
      classification="internal"
      timestamp="2026-04-29T14:03:22Z"
    />
  </div>
);

export const Compact = () => (
  <div style={{ maxWidth: 720 }}>
    <Receipt
      hash="a3f9c2"
      source="subscriptions × accounts"
      owner="ricardo"
      classification="internal"
      timestamp="2026-04-29T14:03:22Z"
      compact
    />
  </div>
);

export const PiiMasked = () => (
  <div style={{ maxWidth: 520 }}>
    <Receipt
      hash="deadbe"
      source="customers (emails masked)"
      owner="alice"
      classification="pii-masked"
    />
  </div>
);
