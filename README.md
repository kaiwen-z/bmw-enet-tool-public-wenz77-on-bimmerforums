# BMW ENET Live Sensor Dashboard - N55 Engine

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20Linux-green.svg)]()
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

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

### Live Dashboard with Log Replay Feature

![Replay GIF](/media/bmw-dashboard.gif)

### Interactive Log Viewer

![Log Viewer](/media/bmwenetlogger.PNG)

---

## 📋 Overview

This project provides a **live, real-time dashboard** for monitoring BMW N55 engine sensors through the ENET (Ethernet) diagnostic interface. Built from scratch after extensive reverse-engineering of BMW's HSFZ/UDS protocol, it delivers professional-grade telemetry without expensive commercial tools.

**Why this exists:** Commercial diagnostic tools are expensive (I was unable to find one without payment) and often don't provide the level of real-time data visualization and logging capability needed for diagnostics. This solution fills that gap with an open-source, customizable alternative. Although this program only supports F chassis N55 engines due to how I reverse engineered the ENET communication protocol, I did not add decoding for every type of sensor. You can request changes or apply them yourself with a github pull request.

**Main problem I was trying to solve:** is figuring out why my engine sometimes stumbles on coldstarts when the weather is below 0c. This happens consistently on every coldstart of the day on my n55, and I wanted to be able to log all the engine information to see what is going on. Unfortunately, I could not find a single free logging tool out there. So I resorted to making my own. 

**Here is the cold start stumble:**
[![Watch the video](https://img.youtube.com/vi/QyVEl4P64RY/maxresdefault.jpg)](https://youtu.be/QyVEl4P64RY)
---

## ✨ Features

- **🔌 Live Sensor Monitoring** - Real-time data from 11+ engine parameters. Disable sensors by clicking on their gauge or the sensor list dropdown
- **💾 CSV Logging** - Timestamped data logging for later analysis. Files are created in the same directory as the livedashboard runs
- **🔄 Log Replay** - Replay recorded sessions with synchronized cursor. ENET will disconnect when replay function is active
- **📈 Interactive Plotter** - Advanced time-series visualization with zoom/pan to help you see the relationship between sensors. Activate / deactivate plotting of sensor data by clicking on their coloured box in the legend.
- **🎯 Auto-Discovery** - Automatic detection of BMW ENET interface. Will scan the usual expected port range from 169.254.x.xxx. Generally all F chassis cars have a similar or same port 6801
- **⚡ High Performance** - Sub-90ms sensor polling intervals. Note that de-activating sensors will make polling faster for all remaining ones.
- **🎨 Dark Theme UI** - Professional "Precision Dark" instrument aesthetic. I love my dark themes.
- **🔧 Configurable Sensors** - Enable/disable individual sensors by clicking on them
- **⚠️ Warning Indicators** - Visual alerts for out-of-range values

---

## 🏗️ Technical Architecture

### TCP packet format:
PC → Car:  00 00 00 05 00 01 f4 12 22 f3 00      (Read DID F300)
Car → PC:  00 00 00 05 00 02 f4 12 22 f3 00      (ZGW echo)
Car → PC:  00 00 00 06 00 01 12 f4 62 f3 00 42   (ECU response: value = 0x42)

PC → Car:  00 00 00 06 00 01 f4 12 2c 03 f3 00   (Define data block by DID F300)
Car → PC:  00 00 00 06 00 02 f4 12 2c 03 f3 00   (ZGW echo)
Car → PC:  00 00 00 06 00 01 12 f4 6c 03 f3 00   (ECU response: block defined)

PC → Car:  00 00 00 0a 00 01 f4 12 2c 01 f3 00 44 02 01 02  (Read data block)
Car → PC:  00 00 00 07 00 02 f4 12 2c 01 f3 00 44            (ZGW echo)
Car → PC:  00 00 00 06 00 01 12 f4 6c 01 f3 00               (ECU response: sending data)

### Protocol Stack

![stack](/media/protocolstack.png)

### Sensor Data Flow

![flowchart](/media/sensorflowchart.png)

            
## 🚀 Development Journey

### Iteration 1: Protocol Discovery