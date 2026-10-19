// A person's photo (or their initial when there is none).
import { h } from "./dom.js";

/** size: "sm" (header), "md" (lists) or "big" (profile). */
export function photoOf(person, size = "md") {
  if (person?.has_photo && person.username) {
    return h("img", {
      class: `photo ${size === "sm" ? "" : size}`,
      src: `/api/people/${encodeURIComponent(person.username)}/photo?v=${person.photo_version || 0}`,
      alt: "",
    });
  }
  const initial = (person?.name || "?").slice(0, 1).toUpperCase();
  if (size === "sm") return h("span", { class: "circle" }, initial);
  return h("span", { class: size === "big" ? "photo-big" : "photo-md", "aria-hidden": "true" }, initial);
}

export const GENDERS = [
  ["prefer_not_to_say", "Prefer not to say"],
  ["female", "Female"],
  ["male", "Male"],
  ["non_binary", "Non-binary"],
];
