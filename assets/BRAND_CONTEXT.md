# VoxWatch – Project Context for AI Assistants

## Overview

VoxWatch is an open-source, self-hosted tool that adds **audio-aware detection** to camera-based surveillance systems, primarily designed to integrate with **Frigate NVR** and homelab environments.

It extends traditional video detection by incorporating **sound events**, enabling richer automation and monitoring.

---

## Target Audience

* Homelab enthusiasts
* Frigate NVR users
* Self-hosted / OSS community
* Developers who prefer lightweight, local-first tools

Tone:

* Technical
* No fluff
* Practical and efficient
* "Built by a developer, for developers"

---

## Core Concept

> "Not just watching — listening."

VoxWatch processes audio streams and correlates them with camera detections.

Examples:

* Glass breaking detection
* Dog barking
* Voices / unusual sound events
* Correlating audio spikes with motion events

---

## Design Philosophy

### Product

* Local-first (no cloud dependency)
* Lightweight and efficient
* Composable with existing tools (Frigate, Home Assistant)
* Transparent and hackable

### Branding

* Minimal, technical, non-corporate
* Avoid "AI startup" aesthetics
* No gradients, no glossy effects
* Should feel at home in a terminal or dashboard

---

## Logo System (V3)

### Concept

Detection box + waveform

Represents:

* Bounding boxes (computer vision / Frigate)
* Audio signal (Vox)
* Combined perception system

---

### Visual Elements

#### 1. Detection Box

* Four corner brackets (not a full square)
* Sharp edges (no rounded corners)
* Represents object detection

#### 2. Waveform

* Centered inside box
* Subtle "V" shape (for Vox)
* Clean, angular (not smooth curves)

#### 3. Typography

* Font: JetBrains Mono (or monospace)
* Lowercase: `voxwatch`
* Slight letter spacing
* No heavy weights

---

## Color System

### Primary

* Blue (brackets): #60A5FA
* Orange (waveform): #F59E0B

### Background

* Dark: #0F172A
* Light: #FFFFFF

### Text

* Primary: #93C5FD
* Muted: #64748B

### Rules

* Max 2–3 colors per composition
* No gradients
* Prefer flat colors

---

## Logo Variants

### Available Files

* logo-dark.svg (primary)
* logo-light.svg
* logo-mono-dark.svg
* logo-mono-light.svg

### Icons

* icon-dark.svg
* icon-light.svg
* app-icon (filled variant)

### Usage

* Dark version is default
* Monochrome for CLI / print
* Icon-only for favicon / containers

---

## UI / UX Direction

### Style

* Dark-first UI
* Grid-based layouts
* Subtle lines and structure (like infra tools)

### Influences

* Frigate
* Home Assistant
* Grafana
* Terminal / CLI tools

---

## Patterns to Use

* Detection brackets as UI motif
* Waveform animations for activity
* Minimal cards and panels
* Monospace labels where appropriate

---

## Patterns to Avoid

* Overly rounded UI
* Bright gradients
* Marketing-style illustrations
* Cartoon mascots (unless explicitly requested)

---

## Messaging

### Good

* "Audio-aware detection"
* "Built for Frigate"
* "Local-first"
* "Lightweight"

### Avoid

* Buzzwords (AI-powered, next-gen, etc.)
* Corporate tone
* Over-promising

---

## Example Taglines

* "Audio-aware surveillance for Frigate"
* "Listen to what your cameras miss"
* "Detection beyond motion"

---

## File Structure (Suggested)

```
/assets
  /logo
  /icons
/docs
  README.md
  VOXWATCH_CONTEXT.md
```

---

## Guidance for AI Assistants

When generating code, UI, or designs:

* Prioritize **clarity and performance**
* Keep visuals **minimal and functional**
* Match **Frigate/Home Assistant ecosystem**
* Avoid unnecessary abstraction or complexity
* Assume user is technical

If unsure:
→ default to simpler, more utilitarian solutions

---

## Summary

VoxWatch is:

* A developer-first tool
* Focused on real utility
* Designed to integrate, not replace
* Built for people who run their own infrastructure

The brand should reflect:

> precision, usefulness, and restraint
