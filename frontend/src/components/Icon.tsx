import icons from '../demo/icons.json';
const outline: Record<string, string> = icons.outline;
const solid: Record<string, string> = icons.solid;
/** Only locally versioned SVG path constants are inserted here. */
export function Icon({name, active = false}: {name: string; active?: boolean}) {
  return <svg className={`icon${active ? ' nav-solid' : ''}`} viewBox="0 0 24 24" aria-hidden="true"
    dangerouslySetInnerHTML={{__html: active ? solid[name] ?? outline.file : outline[name] ?? outline.file}} />;
}
