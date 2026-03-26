import { z } from "zod";

/** Health check response — mirror shape in FastAPI (Pydantic) for the API route. */
export const HealthResponseSchema = z.object({
  status: z.literal("ok"),
  service: z.string(),
  database: z.enum(["sqlite", "postgres"]),
});

export type HealthResponse = z.infer<typeof HealthResponseSchema>;
