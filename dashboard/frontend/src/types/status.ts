/**
 * TypeScript type definitions for VoxWatch system status.
 *
 * These types mirror the Pydantic models returned by GET /api/status.
 * The status endpoint probes Frigate and go2rtc directly and builds the
 * camera list from config.yaml.
 */

/**
 * Speaker/audio-output capability of a camera as determined by the
 * VoxWatch compatibility database or a manual user override.
 *
 * - "built_in"  — camera has a built-in loudspeaker (fully compatible).
 * - "rca_out"   — camera has an RCA audio output but no built-in speaker.
 * - "none"      — camera has no audio output at all (incompatible).
 * - "unknown"   — model not in the VoxWatch database.
 * - "override"  — user confirmed compatibility manually.
 */
export type SpeakerStatus = 'built_in' | 'rca_out' | 'none' | 'unknown' | 'override';

/** Result returned by POST /api/cameras/{name}/identify. */
export interface CameraIdentifyResult {
  /** Whether ONVIF identification succeeded. */
  identified: boolean;
  /** Manufacturer string from ONVIF, e.g. "Dahua". */
  manufacturer: string | null;
  /** Raw model string from ONVIF, e.g. "IPC-T54IR-AS-2.8mm-S3". */
  model: string | null;
  /** Firmware version from ONVIF. */
  firmware: string | null;
  /** IP address that was probed. */
  camera_ip: string | null;
  /** Matched entry from the VoxWatch camera database, or null if unknown. */
  compatibility: CameraCompatibility | null;
  /** Resolved speaker capability. */
  speaker_status: SpeakerStatus;
  /** Error message when identified is false. */
  error: string | null;
}

/** A single entry from the VoxWatch camera compatibility database. */
export interface CameraCompatibility {
  manufacturer: string;
  has_speaker: boolean;
  speaker_type: SpeakerStatus;
  backchannel_codec: string | null;
  tested: boolean;
  notes: string;
  model_key: string;
}

/** Basic status for a single configured camera (from config.yaml). */
export interface CameraStatus {
  /** Frigate camera name (matches config key). */
  name: string;
  /** Whether the camera is enabled in VoxWatch config. */
  enabled: boolean;
  /** Whether Frigate reports this camera as online. */
  frigate_online?: boolean;
  /** Current detection FPS reported by Frigate. */
  fps?: number;
  /** Whether go2rtc reports a backchannel (two-way audio) track. */
  has_backchannel?: boolean;
  /** Supported backchannel audio codecs (e.g. ["PCMU/8000"]). */
  backchannel_codecs?: string[];
  /** ISO timestamp of last detection on this camera. */
  last_detection_at?: string;
  /** Pipeline latency in ms for the last detection. */
  last_latency_ms?: number;
  /** Raw model string returned by ONVIF GetDeviceInformation. */
  camera_model?: string;
  /** Manufacturer name from ONVIF or camera_db. */
  camera_manufacturer?: string;
  /**
   * Speaker/audio-output capability resolved from the compatibility database.
   * Populated after a successful POST /api/cameras/{name}/identify.
   */
  speaker_status?: SpeakerStatus;
  /** Human-readable compatibility notes from camera_db or ONVIF probe. */
  compatibility_notes?: string;
}

/** Status of the Frigate NVR as reported by its API. */
export interface FrigateStatus {
  reachable: boolean;
  version?: string;
  camera_count?: number;
  uptime_seconds?: number;
  error?: string;
}

/** Status of the go2rtc relay as reported by its API. */
export interface Go2rtcStatus {
  reachable: boolean;
  version?: string;
  stream_count?: number;
  error?: string;
}

/**
 * Top-level status response from GET /api/status.
 *
 * Aggregates Frigate, go2rtc, and per-camera information.
 * Aliased as ServiceStatus so existing hook consumers need minimal changes.
 */
export interface ServiceStatus {
  /** ISO 8601 timestamp when this snapshot was assembled. */
  timestamp: string;
  /** Frigate NVR status. */
  frigate: FrigateStatus;
  /** go2rtc relay status. */
  go2rtc: Go2rtcStatus;
  /** Per-camera status derived from config.yaml. */
  cameras: CameraStatus[];
}
