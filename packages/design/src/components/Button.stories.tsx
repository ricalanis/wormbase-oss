import "../styles.css";
import { Button } from "./Button";

export const Primary = () => (
  <Button onClick={() => void 0}>Create demo workspace</Button>
);

export const Secondary = () => (
  <Button variant="secondary">Back</Button>
);

export const Danger = () => (
  <Button variant="danger">Block execution (PII detected)</Button>
);

export const Ghost = () => <Button variant="ghost">Skip for now</Button>;

export const Sizes = () => (
  <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
    <Button size="sm">Small</Button>
    <Button size="md">Medium</Button>
    <Button size="lg">Large</Button>
  </div>
);
