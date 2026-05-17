import { Wordmark } from "./Wordmark";

export default { title: "Brand / Wordmark" };

export const Default = () => <Wordmark />;

export const Tall = () => <Wordmark height={48} />;

export const NoRule = () => <Wordmark height={32} rule={false} />;

export const Green = () => <Wordmark color="#2C5F3E" />;
