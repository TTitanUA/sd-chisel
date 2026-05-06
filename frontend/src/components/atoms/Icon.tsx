import {
  AlertCircle,
  BrushCleaning,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Copy,
  Eye,
  EyeOff,
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
  Shield,
  Sparkles,
  Star,
  Trash2,
  Workflow,
  X,
  type LucideIcon,
} from "lucide-react";

const ICONS = {
  AlertCircle,
  BrushCleaning,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Copy,
  Eye,
  EyeOff,
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
  Shield,
  Sparkles,
  Star,
  Trash2,
  Workflow,
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
