import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Folder,
  Link,
  MessageSquare,
  Pencil,
  Pin,
  Plus,
  RotateCw,
  Search,
  Send,
  Server,
  Settings,
  Sparkles,
  Trash2,
  X,
  type LucideIcon,
} from "lucide-react";

const ICONS = {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Copy,
  Folder,
  Link,
  MessageSquare,
  Pencil,
  Pin,
  Plus,
  RotateCw,
  Search,
  Send,
  Server,
  Settings,
  Sparkles,
  Trash2,
  X,
} as const satisfies Record<string, LucideIcon>;

export type IconName = keyof typeof ICONS;

export function Icon({
  name,
  size = 14,
  strokeWidth = 1.75,
  ...rest
}: {
  name: IconName;
  size?: number;
  strokeWidth?: number;
  className?: string;
  "aria-label"?: string;
}) {
  const Cmp = ICONS[name];
  return <Cmp size={size} strokeWidth={strokeWidth} {...rest} />;
}
