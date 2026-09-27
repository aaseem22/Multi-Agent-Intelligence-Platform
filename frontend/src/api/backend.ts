// Picks the live client or the scripted mock. VITE_USE_MOCK=true switches to the mock.

import { httpBackend } from "./http";
import { mockBackend } from "./mock";
import type { Backend } from "./types";

export const backend: Backend = import.meta.env.VITE_USE_MOCK === "true" ? mockBackend : httpBackend;
