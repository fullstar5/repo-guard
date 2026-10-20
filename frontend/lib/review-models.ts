/** Short labels for the manual review model picker. Unknown ids show as-is. */
export function reviewModelLabel(modelName: string): string {
  if (modelName === "openrouter/free") {
    return "Free router";
  }
  if (modelName === "nvidia/nemotron-3-ultra-550b-a55b:free") {
    return "Nemotron 3 Ultra";
  }
  if (modelName === "nvidia/nemotron-3.5-super-vl:free") {
    return "Nemotron 3.5 Super";
  }
  return modelName;
}
