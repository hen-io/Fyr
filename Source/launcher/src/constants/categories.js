import { mdiMultimedia, mdiSecurity } from "@mdi/js";

// apps.config (backend) only knows a category as a plain name string - which
// MDI icon represents it is a frontend presentation concern, so it lives
// here instead. A category with no entry just renders without an icon.
export const CATEGORY_ICONS = {
  Mediebehandling: mdiMultimedia,
  Management: mdiSecurity,
};
