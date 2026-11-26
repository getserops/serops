// The "Min severity" floor of a delivery channel or a routing rule (1.5.6).
// Issues carry CRITICAL, WARNING, INFO or UNKNOWN, so the choices are those
// levels. Floors saved before 1.5.6 hold LOW, MEDIUM or HIGH; each one shows
// as the level the server now treats it as. Anything else shows as "any",
// which is how the server treats it.
export const FLOOR_CHOICES = ["", "INFO", "WARNING", "CRITICAL"];

const EQUIVALENT = {
  INFO: "INFO",
  LOW: "INFO",
  WARNING: "WARNING",
  MEDIUM: "WARNING",
  CRITICAL: "CRITICAL",
  HIGH: "CRITICAL",
};

// The choice to show for a stored floor.
export function floorChoice(stored) {
  return EQUIVALENT[String(stored ?? "").trim().toUpperCase()] || "";
}

// The value to save: the level's own word (INFO, WARNING, CRITICAL), so an
// old floor is rewritten in the new words when its form is saved. The 1.5.6
// server accepts them on channels and rules alike.
export function floorToSave(choice) {
  return floorChoice(choice);
}
