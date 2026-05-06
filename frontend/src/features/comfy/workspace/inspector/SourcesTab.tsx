import type { Session } from "@/api/sessions";
import { SourceImagesPane } from "@/components/organisms/SourceImagesPane";

/** Sources rail tab — image upload + thumbnails. The shared
 *  `SourceImagesPane` already covers the comfy case (it skips the
 *  is_main UI when `session_type !== "i2i"`). The Bindings tab will
 *  drag-or-pick from these thumbnails in Live PR. */
export function SourcesTab({ session }: { session: Session }) {
  return <SourceImagesPane session={session} />;
}
