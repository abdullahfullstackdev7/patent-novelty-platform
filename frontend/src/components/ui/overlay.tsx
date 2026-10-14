import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as ToastPrimitive from "@radix-ui/react-toast";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

// ---- Dialog and Sheet --------------------------------------------------------------------------

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
export const DialogTitle = DialogPrimitive.Title;
export const DialogDescription = DialogPrimitive.Description;

export const DialogContent = React.forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & { side?: "center" | "right" }
>(({ className, children, side = "center", ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-navy/50" />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        "fixed z-50 bg-white p-6 shadow-xl",
        side === "center" && "left-1/2 top-1/2 w-[calc(100%-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 rounded-2xl",
        side === "right" && "inset-y-0 right-0 w-[min(22rem,100%)] overflow-y-auto",
        className,
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close
        className="absolute right-4 top-4 rounded-md p-1 text-stone-600 hover:bg-stone-100"
        aria-label="Close"
      >
        <X className="h-5 w-5" aria-hidden="true" />
      </DialogPrimitive.Close>
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
));
DialogContent.displayName = "DialogContent";

/** A Sheet is a Dialog that slides in from the right edge. */
export const Sheet = Dialog;
export const SheetTrigger = DialogTrigger;
export const SheetClose = DialogClose;
export const SheetContent = (props: React.ComponentPropsWithoutRef<typeof DialogContent>) => (
  <DialogContent side="right" {...props} />
);

// ---- Tooltip -----------------------------------------------------------------------------------

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;
export const TooltipContent = ({
  className,
  ...props
}: React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      sideOffset={6}
      className={cn("z-50 max-w-xs rounded-md bg-navy px-3 py-1.5 text-sm text-white", className)}
      {...props}
    />
  </TooltipPrimitive.Portal>
);

// ---- Toast -------------------------------------------------------------------------------------

export const ToastProvider = ToastPrimitive.Provider;

export function Toast({
  title,
  description,
  tone = "success",
  ...props
}: React.ComponentPropsWithoutRef<typeof ToastPrimitive.Root> & {
  title: string;
  description?: string;
  tone?: "success" | "error";
}) {
  return (
    <ToastPrimitive.Root
      className={cn(
        "rounded-xl border bg-white p-4 shadow-xl",
        tone === "success" ? "border-green-300" : "border-red-300",
      )}
      {...props}
    >
      <ToastPrimitive.Title className="font-semibold text-navy">{title}</ToastPrimitive.Title>
      {description && (
        <ToastPrimitive.Description className="mt-1 text-sm text-stone-700">{description}</ToastPrimitive.Description>
      )}
    </ToastPrimitive.Root>
  );
}

export const ToastViewport = () => (
  <ToastPrimitive.Viewport className="fixed bottom-4 right-4 z-[60] flex w-[min(24rem,calc(100%-2rem))] flex-col gap-2" />
);
