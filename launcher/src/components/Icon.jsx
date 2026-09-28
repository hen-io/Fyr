import { Icon } from "@mdi/react";

export function Mdi({ path, size = 1, color = "currentColor" }) {
  if (!path) return null;
  return <Icon path={path} size={size} color={color} />;
}
