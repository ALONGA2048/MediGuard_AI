/** Shared contracts for the web client, cloud API, and Raspberry Pi agent. */
export type DeviceStatus = "online" | "offline" | "busy";
export type LightMode = "white" | "warm" | "uv" | "off";
export type CommandType = "set_light" | "capture" | "shutdown_lights";

export interface DeviceCommand {
  commandId: string;
  deviceId: string;
  type: CommandType;
  createdAt: string;
  expiresAt: string;
  payload: { lightMode?: LightMode; brightness?: number; captureId?: string; sendToServer?: boolean };
}

export interface DeviceCommandResult {
  commandId: string;
  status: "accepted" | "running" | "completed" | "failed";
  completedAt?: string;
  imageUrl?: string;
  errorCode?: string;
}

export interface DrugSummary {
  id: string;
  licenseNumber: string;
  nameZh: string;
  nameEn?: string;
  ingredient: string;
  indication: string;
  dosage?: string;
  precautions?: string;
  source: "TFDA" | "pharmacist_reviewed";
  sourceUpdatedAt: string;
}

export interface PrescriptionImportResult {
  importId: string;
  status: "queued" | "processing" | "needs_review" | "confirmed" | "failed";
  sourceFileUrl?: string;
  lowConfidenceFields: string[];
}
