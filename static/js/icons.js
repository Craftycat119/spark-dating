// Набор иконок (stroke-иконки 24×24)
const p = (d, extra = "") =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`;

export const icons = {
  heart: p('<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" fill="currentColor"/>'),
  x: p('<path d="M6 6l12 12M18 6L6 18" stroke-width="2.6"/>'),
  flame: p('<path d="M12 21c4 0 7-2.7 7-6.6 0-3.6-2.6-5.6-3.6-8.4-1.6 1.4-2 3-2 4.2C11.8 8.5 10.5 5.6 8 3c.3 3.4-3 6.3-3 11.4C5 18.3 8 21 12 21z"/>'),
  chat: p('<path d="M20 12a8 8 0 0 1-11.6 7.1L4 20l1-4.2A8 8 0 1 1 20 12z"/>'),
  user: p('<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>'),
  back: p('<path d="M15 5l-7 7 7 7"/>'),
  phone: p('<path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2z"/>'),
  video: p('<rect x="3" y="6" width="13" height="12" rx="3"/><path d="M16 10l5-3v10l-5-3z"/>'),
  videoOff: p('<path d="M3 3l18 18M16 16v1a1 1 0 0 1-1 1H6a3 3 0 0 1-3-3V9a3 3 0 0 1 2-2.8M10 6h5a1 1 0 0 1 1 1v3l5-3v10"/>'),
  mic: p('<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/>'),
  micOff: p('<path d="M3 3l18 18M9 9v2a3 3 0 0 0 5 2.2M15 10V6a3 3 0 0 0-5.7-1.3M5 11a7 7 0 0 0 11 5.7M19 11a7 7 0 0 1-.6 2.8M12 18v3"/>'),
  hang: p('<path d="M3 14c5-5 13-5 18 0l-2 3-4-1v-3a10 10 0 0 0-6 0v3l-4 1z" fill="currentColor"/>'),
  clip: p('<path d="M20 11l-8.5 8.5a5 5 0 0 1-7-7L13 4a3.5 3.5 0 0 1 5 5l-8.4 8.4a2 2 0 0 1-2.8-2.8L14.5 7"/>'),
  smile: p('<circle cx="12" cy="12" r="9"/><path d="M8.5 14.5a4.5 4.5 0 0 0 7 0M9 9.5h.01M15 9.5h.01" stroke-width="2.4"/>'),
  send: p('<path d="M4 12l16-8-6 17-3-7z" fill="currentColor"/>'),
  circle: p('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4" fill="currentColor"/>'),
  play: p('<path d="M7 4l13 8-13 8z" fill="currentColor" stroke="none"/>'),
  pause: p('<path d="M7 4h3v16H7zM14 4h3v16h-3z" fill="currentColor" stroke="none"/>'),
  check: p('<path d="M4 12.5l5 5L20 6.5" stroke-width="2.6"/>'),
  shield: p('<path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>'),
  pin: p('<path d="M12 21s-7-6.2-7-12a7 7 0 0 1 14 0c0 5.8-7 12-7 12z"/><circle cx="12" cy="9" r="2.5"/>'),
  more: p('<circle cx="5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="19" cy="12" r="1.3" fill="currentColor"/>'),
  camera: p('<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/>'),
  flip: p('<path d="M4 9a8 8 0 0 1 14-3l2 2M20 15a8 8 0 0 1-14 3l-2-2M20 4v4h-4M4 20v-4h4"/>'),
};
