/**
 * One Material Symbol.
 *
 * The mockup writes these as `<span class="material-symbols-outlined">name</span>`;
 * this wraps that so the glyph name is a prop and every icon is hidden from the
 * accessibility tree, which is right for all of them — each one sits beside a
 * label or on a button that carries its own aria-label.
 */
export default function Icon({ name, className = '', filled = false }) {
  return (
    <span
      className={`material-symbols-outlined ${className}`}
      style={filled ? { fontVariationSettings: "'FILL' 1" } : undefined}
      aria-hidden="true"
    >
      {name}
    </span>
  )
}
