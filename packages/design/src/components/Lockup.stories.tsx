import { Lockup } from "./Lockup";

export default { title: "Brand / Lockup" };

export const Horizontal = () => <Lockup orientation="horizontal" />;

export const Stacked = () => <Lockup orientation="stacked" />;

export const HorizontalNoReceipt = () => (
  <Lockup orientation="horizontal" withReceipt={false} />
);

export const Custom = () => (
  <Lockup orientation="horizontal" tagline="DEMO MODE · VOL. I" />
);
