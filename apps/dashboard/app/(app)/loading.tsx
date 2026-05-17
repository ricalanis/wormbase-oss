/**
 * Route-group loading boundary — Next.js automatically renders this while
 * the matched server component is fetching data (W3.A14).
 *
 * The PageSkeleton chrome is the field-notebook loading surface so the
 * operator never sees a blank pane. Per-tab pages may override with their
 * own `loading.tsx` if they want finer copy.
 *
 * Sister W3.A14 also wraps individual page content in PageSuspenseBoundary
 * for inline suspending children (data-product detail drawers, MCP catalog
 * panel, etc.). The route-group loader is the outer net.
 */
import { PageSkeleton } from "../../components/chrome/PageSkeleton";

export default function AppGroupLoading() {
  return <PageSkeleton />;
}
