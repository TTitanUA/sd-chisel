import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";
import styles from "./Button.module.css";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "secondary" | "primary";
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
};

export const Button = forwardRef<HTMLButtonElement, Props>(
  ({ variant = "secondary", size = "md", icon, className, children, ...rest }, ref) => {
    const cls = [
      styles.button,
      variant === "primary" ? styles.primary : null,
      size === "sm" ? styles.sm : size === "lg" ? styles.lg : null,
      className,
    ]
      .filter(Boolean)
      .join(" ");
    return (
      <button ref={ref} className={cls} {...rest}>
        {icon}
        {children}
      </button>
    );
  },
);
Button.displayName = "Button";
