# Odins Eye

**Full Design Process**: [Blueprint Project](https://blueprint.hackclub.com/projects/413)

A compact speed detection system using a Raspberry Pi and a TF-Luna LiDAR sensor monitors vehicles in real time. When a vehicle is detected passing by, the system measures its speed and triggers the Raspberry Pi Camera Module 3 to capture an image.

Captured images are processed locally on a Raspberry Pi Zero 2 W, where the system identifies the vehicle and, when applicable, extracts license plate information. With built-in Wi-Fi connectivity, the unit wirelessly transmits speed data and image results directly to your phone. The entire system is designed to operate autonomously, combining precise sensing, on-device image analysis, and seamless wireless communication in a compact DIY build.

## Features

- **Vehicle Speed Detection:** Real-time speed measurement using a TF-Luna LiDAR sensor
- **Automatic Photo Capture:** Raspberry Pi Camera Module 3 captures an image when a vehicle passes
- **On-Device Processing:** Raspberry Pi Zero 2 W analyzes captured images locally
- **Vehicle Recognition:** Detects vehicles within the captured image
- **License Plate Detection:** Extracts license plate information when a car is detected
- **Wireless Notifications:** Sends captured data and images directly to your phone over WiFi
- **OLED Display:** Shows detected speed and system status directly on the device
- **Autonomous Operation:** Runs continuously without manual interaction
- **Compact DIY Design:** Designed as a small, self-contained monitoring system

## Hardware/BOM

| Component | Qty | Type |
|-----------|-----|------|
| Raspberry Pi Zero 2 W | 1 | Controller |
| Raspberry Pi Camera Module 3 | 1 | Camera Module |
| TF-Luna LiDAR Sensor | 1 | LiDAR Sensor |
| 0.95-inch OLED Display | 1 | Display |
| MPU6050 IMU | 1 | Sensor |
| microSD Card (32GB) | 1 | Storage |
| Custom Carrier PCB | 1 | PCB |
| Custom 3D Printed Case | 1 | Enclosure |
| Power Bank | 1 | Power |
| USB-A to USB-C Cable | 1 | Cable |
| Universal Tripod | 1 | Mount |
| Green LED Power Indicator | 1 | Indicator |
| Mounting Hardware (Assorted Screws) | 1 | Hardware |

## CAD Screenshots

| CAD Assembly (Front View)| CAD Assembly (Back View) |
|-------------------------------|-------------------------------|
| ![Assembly Model Front](screenshots/assembly-model-front.png) | ![Assembly Model Back](screenshots/assembly-model-back.png) |

| 3D Case (Side View) | 3D Case (Side View) |
|----------------------|---------------------|
| ![3D Case Side](screenshots/3d-case-1.png) | ![3D Case Side](screenshots/3d-case-2.png) |

## PCB Screenshots

| PCB Layout |
|-------------------------------|
| ![PCB Layout](screenshots/pcb-design.png) |

| PCB 3D View (Front) | PCB 3D View (Back) |
|----------------------|---------------------|
| ![PCB 3D View (Front)](screenshots/pcb-3d-view-front.png) | ![PCB 3D View (Back)](screenshots/pcb-3d-view-back.png) |


## Usage
Place the system facing the road and use the built-in gyroscope to help align the device at the correct angle for accurate measurements. The TF-Luna LiDAR sensor detects passing vehicles and calculates their speed, triggering the camera to capture an image as a vehicle passes. The Raspberry Pi then processes the image to detect the vehicle and extract the license plate if possible, sending the results to your phone over WiFi. The detected speed and system status are also displayed on the integrated OLED screen, allowing you to quickly view results directly on the device.

## Odins Eye In Action

| Complete Assembly (Front View)| Complete Assembly (Front View) |
|-------------------------------|-------------------------------|
| ![Complete Assembly Front View](screenshots/complete-assembly-front-view-1.jpg) | ![Complete Assembly Front View](screenshots/complete-assembly-front-view-2.jpg) |

| Complete Assembly (Top View)| Complete Assembly (Side View) |
|-----------------------------|-------------------------------|
| ![Complete Assembly Top View](screenshots/complete-assembly-top-view.jpg) | ![Complete Assembly Side View](screenshots/complete-assembly-side-view.jpg) |

| Complete Assembly (Back View)| Complete Assembly (Back View) |
|------------------------------|-------------------------------|
| ![Complete Assembly Back View](screenshots/complete-assembly-back-view-1.jpg) | ![Complete Assembly Back View](screenshots/complete-assembly-back-view-2.jpg) |

## License

MIT License

---

> GitHub [@adrirubio](https://github.com/adrirubio) &nbsp;&middot;&nbsp;
