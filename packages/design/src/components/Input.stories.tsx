import "../styles.css";
import { Input } from "./Input";

export const Default = () => (
  <div style={{ maxWidth: 420 }}>
    <Input
      label="Company name"
      defaultValue="DemoCorp"
      helperText="The name the worm will use when addressing your team."
    />
  </div>
);

export const WithHelper = () => (
  <div style={{ maxWidth: 420 }}>
    <Input
      label="Tenant slug"
      placeholder="democorp"
      helperText="Lowercase, no spaces. Used in URLs and ledger keys."
    />
  </div>
);

export const WithError = () => (
  <div style={{ maxWidth: 420 }}>
    <Input
      label="Slack bot token"
      defaultValue="xoxb-invalid"
      error="Token failed verification. Re-paste the bot user token from Slack."
    />
  </div>
);
