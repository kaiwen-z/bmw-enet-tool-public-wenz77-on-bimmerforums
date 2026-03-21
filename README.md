# bmw-enet-tool-public-wenz77-on-bimmerforums
This repository contains the source code and documentation of the development process of the bmw enet tool for the f10 chassis.  


# BMW ENET Live Sensor Dashboard - N55 Engine

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-green.svg)]()
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)]()

**Real-time engine sensor monitoring for BMW N55 engines via ENET interface**

---

## 📖 Table of Contents

- [Demo](#demo)
- [Overview](#overview)
- [Features](#features)
- [Technical Architecture](#technical-architecture)
- [Development Journey](#development-journey)
- [Challenges & Solutions](#challenges--solutions)
- [Installation](#installation)
- [Usage](#usage)
- [Supported Sensors](#supported-sensors)
- [Log Viewer](#log-viewer)
- [Contributing](#contributing)
- [License](#license)

---

## 🎬 Demo

### Live Dashboard

![Dashboard Screenshot](/media/dashboard_screenshot.png)

### Real-time Sensor Polling

![Live Polling GIF](/media/live_polling.gif)

### Log Replay Feature

![Replay GIF](/media/log_replay.gif)

### Interactive Log Viewer

![Log Viewer](/media/log_viewer.png)

---

## 📋 Overview

This project provides a **live, real-time dashboard** for monitoring BMW N55 engine sensors through the ENET (Ethernet) diagnostic interface. Built from scratch after extensive reverse-engineering of BMW's HSFZ/UDS protocol, it delivers professional-grade telemetry without expensive commercial tools.

**Why this exists:** Commercial diagnostic tools are expensive and often don't provide the level of real-time data visualization needed for performance tuning and diagnostics. This solution fills that gap with an open-source, customizable alternative.

---

## ✨ Features

- **🔌 Live Sensor Monitoring** - Real-time data from 11+ engine parameters
- **📊 Multiple Gauge Types** - Circular, digital, and horizontal bar gauges
- **💾 CSV Logging** - Timestamped data logging for later analysis
- **🔄 Log Replay** - Replay recorded sessions with synchronized cursor
- **📈 Interactive Plotter** - Advanced time-series visualization with zoom/pan
- **🎯 Auto-Discovery** - Automatic detection of BMW ENET interface
- **⚡ High Performance** - Sub-50ms sensor polling intervals
- **🎨 Dark Theme UI** - Professional "Precision Dark" instrument aesthetic
- **🔧 Configurable Sensors** - Enable/disable individual sensors
- **⚠️ Warning Indicators** - Visual alerts for out-of-range values

---

## 🏗️ Technical Architecture

### Protocol Stack
