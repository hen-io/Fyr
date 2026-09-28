import { useState } from "react";

// Drag a fixed-position element from an anchor point. Returns [style, onDragStart]:
// spread `style` onto the element and wire `onDragStart` to its grip's onMouseDown.
export function useDraggable(initialPosition, elementRef) {
  const [position, setPosition] = useState(null);

  const onDragStart = (e) => {
    e.preventDefault();
    const rect = elementRef.current.getBoundingClientRect();
    const offsetX = e.clientX - rect.left;
    const offsetY = e.clientY - rect.top;
    const { width, height } = rect;

    const onMove = (moveEvent) => {
      const x = Math.min(Math.max(0, moveEvent.clientX - offsetX), window.innerWidth - width);
      const y = Math.min(Math.max(0, moveEvent.clientY - offsetY), window.innerHeight - height);
      setPosition({ x, y });
    };

    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };

    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const style = position
    ? { position: "fixed", left: position.x, top: position.y }
    : { position: "fixed", ...initialPosition };

  return [style, onDragStart];
}
