/**
 * One consistent icon system for the whole app — replaces the emoji
 * glyphs that used to be scattered everywhere. Emoji render with
 * different weight/color/style per OS and font, which is exactly what
 * makes an interface read as "generic AI wrapper" rather than a
 * considered product; a single-stroke, single-color SVG set reads as
 * deliberate regardless of what device or OS renders it.
 *
 * Usage: <Icon name="search" /> — size/color inherit from CSS
 * (width/height default to 1em, stroke uses currentColor).
 */
const PATHS = {
  plus: "M12 5v14M5 12h14",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16ZM21 21l-4.35-4.35",
  "message-circle": "M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5Z",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM3.6 9h16.8M3.6 15h16.8M12 3a15 15 0 0 1 3.5 9 15 15 0 0 1-3.5 9 15 15 0 0 1-3.5-9A15 15 0 0 1 12 3Z",
  flask: "M9 2v6.3a2 2 0 0 1-.4 1.2L4 16.5A2 2 0 0 0 5.6 20h12.8a2 2 0 0 0 1.6-3.5l-4.6-7A2 2 0 0 1 15 8.3V2M8 2h8M8.5 14h7",
  bot: "M12 8V4M8 4h8M6 8h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2ZM9 13v1M15 13v1M8 21h1M15 21h1",
  users: "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75",
  paperclip: "M21.4 11.1 12.6 20a5 5 0 0 1-7.1-7.1l9.2-9.2a3.5 3.5 0 0 1 5 5l-9.2 9.2a2 2 0 0 1-2.9-2.9l8.5-8.4",
  mic: "M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3ZM19 10v1a7 7 0 0 1-14 0v-1M12 18v4M9 22h6",
  "mic-off": "M2 2l20 20M16.5 11.5V5a3 3 0 0 0-5.9-.8M9 9v2a3 3 0 0 0 4.3 2.7M19 10v1a7 7 0 0 1-1 3.6M5 10v1a7 7 0 0 0 11.7 5.2M12 18v4M9 22h6",
  square: "M6 6h12v12H6z",
  send: "m3 3 18 9-18 9 4-9-4-9Z",
  "chevron-down": "m6 9 6 6 6-6",
  "chevron-up": "m18 15-6-6-6 6",
  "chevron-left": "m15 18-6-6 6-6",
  "chevron-right": "m9 18 6-6-6-6",
  sun: "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10Z",
  moon: "M20.8 14.7A9 9 0 1 1 9.3 3.2a7 7 0 0 0 11.5 11.5Z",
  "volume-2": "M11 5 6 9H2v6h4l5 4V5ZM19.1 4.9a10 10 0 0 1 0 14.1M15.5 8.5a5 5 0 0 1 0 7",
  "volume-x": "M11 5 6 9H2v6h4l5 4V5ZM23 9l-6 6M17 9l6 6",
  command: "M9 4a2.5 2.5 0 1 0-2.5 2.5H9V4ZM9 4v16M9 20a2.5 2.5 0 1 1-2.5-2.5H9V20ZM15 4a2.5 2.5 0 1 1 2.5 2.5H15V4ZM15 4v16M15 20a2.5 2.5 0 1 0 2.5-2.5H15V20ZM6.5 6.5h11M6.5 17.5h11",
  "panel-left": "M4 4h16v16H4zM10 4v16",
  folder: "M4 6a2 2 0 0 1 2-2h4l2 3h6a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6Z",
  "folder-open": "M4 6a2 2 0 0 1 2-2h4l2 3h6a2 2 0 0 1 2 2v1H8l-3 8H4V6Z M6 12l-2 8h14l3-8H6Z",
  image: "M4 5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5ZM9 11a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM4 17l5-5 3 3 4-5 4 6",
  video: "M4 6a1 1 0 0 1 1-1h9a1 1 0 0 1 1 1v12a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6ZM21 8.5 15 12l6 3.5v-7Z",
  "file-text": "M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-6ZM14 2v6h6M9 13h6M9 17h6M9 9h1",
  headphones: "M3 14v-2a9 9 0 0 1 18 0v2M21 14a2 2 0 0 1-2 2h-1a1 1 0 0 1-1-1v-4a1 1 0 0 1 1-1h1a2 2 0 0 1 2 2v2ZM3 14a2 2 0 0 0 2 2h1a1 1 0 0 0 1-1v-4a1 1 0 0 0-1-1H5a2 2 0 0 0-2 2v2Z",
  terminal: "m4 17 6-5-6-5M12 19h8",
  "book-open": "M12 7a4 4 0 0 0-4-2H3v13h5a4 4 0 0 1 4 2M12 7a4 4 0 0 1 4-2h5v13h-5a4 4 0 0 0-4 2M12 7v14",
  "file-pen": "M14 2H7a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h5.5M14 2v6h6M13.5 22l1-3.5 5-5a1.4 1.4 0 0 1 2 2l-5 5-3 1Z",
  link: "M9 17H7A5 5 0 0 1 7 7h2M15 7h2a5 5 0 1 1 0 10h-2M8 12h8",
  wrench: "M14.7 6.3a4 4 0 1 1-8.4 4l-4.6 4.6a2 2 0 0 0 2.8 2.8l4.6-4.6a4 4 0 0 1 5.6-6.8Z",
  pencil: "M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7M18.4 2.6a2 2 0 1 1 2.8 2.8L11 15.7 7 16.7l1-4 10.4-10.1Z",
  check: "M20 6 9 17l-5-5",
  x: "M18 6 6 18M6 6l12 12",
  "alert-triangle": "M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0ZM12 9v4M12 17h.01",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 16v-5M12 8h.01",
  "rotate-ccw": "M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM19.4 15a1.65 1.65 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.65 1.65 0 0 0-1.8-.3 1.65 1.65 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.65 1.65 0 0 0-1-1.5 1.65 1.65 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.65 1.65 0 0 0 .3-1.8 1.65 1.65 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.65 1.65 0 0 0 1.5-1 1.65 1.65 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.65 1.65 0 0 0 1.8.3H9a1.65 1.65 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.65 1.65 0 0 0 1 1.5 1.65 1.65 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.65 1.65 0 0 0-.3 1.8V9a1.65 1.65 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.65 1.65 0 0 0-1.5 1Z",
  masks: "M8.5 3a5.5 5.5 0 0 0-5.5 5.5c0 3 2 5.6 3.5 7.3.8.9 2 1.2 3 .6M8 10c.5-1 1.8-1 2.3 0M4.5 12.5c1 .5 2 .5 3 0M15.5 3a5.5 5.5 0 0 1 5.5 5.5c0 3-2 5.6-3.5 7.3-.8.9-2 1.2-3 .6M16 10c-.5-1-1.8-1-2.3 0M19.5 12.5c-1 .5-2 .5-3 0M9 21c1-1.2 2-2 3-2s2 .8 3 2",
  grid: "M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 7v5l3 3",
  download: "M12 3v12M7 10l5 5 5-5M4 20h16",
  hourglass: "M6 2h12M6 22h12M6 2c0 5 4 6 6 8-2 2-6 3-6 8M18 2c0 5-4 6-6 8 2 2 6 3 6 8",
  menu: "M4 6h16M4 12h16M4 18h16",
  target: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10ZM12 13a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z",
  bolt: "M13 2 3 14h7l-1 8 11-14h-7l0-6Z",
  layers: "m12 2 9 5-9 5-9-5 9-5ZM3 12l9 5 9-5M3 17l9 5 9-5",
  "git-branch": "M6 3v12M18 9a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM6 21a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM18 9a9 9 0 0 1-9 9",
  "check-circle": "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM8.5 12l2.5 2.5 4.5-5",
  copy: "M9 9h11a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H9a1 1 0 0 1-1-1V10a1 1 0 0 1 1-1ZM5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h11a1 1 0 0 1 1 1v1",
  share: "M18 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM6 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM18 22a3 3 0 1 0 0-6 3 3 0 0 0 0 6ZM8.6 13.5l6.8 4M15.4 6.5l-6.8 4",
  trash: "M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1L5 6M10 11v6M14 11v6",
};

export default function Icon({ name, size = 16, className = "", ...rest }) {
  const d = PATHS[name];
  if (!d) return null;
  return (
    <svg
      className={`icon icon-${name} ${className}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...rest}
    >
      <path d={d} />
    </svg>
  );
}
