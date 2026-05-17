import { WormMark } from "./WormMark";

export default { title: "Brand / WormMark" };

export const Default = () => <WormMark size={180} />;

export const Outline = () => <WormMark size={180} mode="outline" />;

export const Negative = () => (
  <div style={{ background: "#2A2A2A", padding: 24 }}>
    <WormMark size={180} mode="negative" />
  </div>
);

export const NoArc = () => <WormMark size={140} showArc={false} />;

export const NoTicks = () => <WormMark size={140} ticks={false} />;

export const SmallFavicon = () => <WormMark size={32} showArc={false} ticks={false} />;
