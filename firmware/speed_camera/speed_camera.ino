#include <Arduino.h>
#include <Wire.h>        // Instantiate the Wire library
#include <TFLI2C.h>      // TFLuna-I2C Library v.0.1.1
#include <math.h>        // For cos() function

TFLI2C tflI2C;

int16_t  tfDist;                        // Distance in centimeters (library output)
int16_t  tfFlux;                        // Signal strength (0-65535)
int16_t  tfTemp;                        // Temperature (not used)
int16_t  tfAddr = TFL_DEF_ADR;          // Default I2C address for TF-Luna

// ======================= CONFIGURATION =======================
const float ANGLE_DEGREES = 20.0;       // Angle of camera facing the road (degrees)
const float COS_ANGLE = cos(ANGLE_DEGREES * PI / 180.0);  // Pre-calculated cosine

const float GAP_TIME_MS = 30.0;         // Gap between burst 1 and burst 2 (milliseconds) - SHORT for fast objects

const int BURST_SIZE = 3;               // Number of measurements per burst
const float BASELINE_TOLERANCE_CM = 10.0; // Tolerance for baseline comparison (cm)

// Detection lock timeout - prevents system from hanging
const unsigned long DETECTION_TIMEOUT_MS = 5000;  // 5 seconds

// Speed validation thresholds
const float MIN_DISTANCE_CHANGE_M = 0.05;  // Minimum distance change to be valid (5cm) - LOWERED for fast objects
const float MAX_DISTANCE_CHANGE_M = 3.0;   // Maximum distance change (3m - sanity check)
const float MIN_SPEED_KMH = 5.0;           // Reject speeds below 5 km/h (probably noise/walking)
const float MAX_SPEED_KMH = 200.0;         // Reject speeds above 200 km/h (probably error)

// Signal strength threshold
const int MIN_SIGNAL_STRENGTH = 50;        // Minimum flux value for valid reading - LOWERED for better detection

// Debug mode - set to true for detailed diagnostics
const bool DEBUG_MODE = true;

// Baseline distance - set to 0 if no wall within range, otherwise the wall distance
float baselineDistance = 0.0;           // Will be calibrated on startup (in meters)
bool baselineSet = false;

// Detection lock - prevents multiple readings of same vehicle
bool detectionLocked = false;           // True after a vehicle is detected, until baseline restored
unsigned long lockStartTime = 0;        // Time when lock started (for timeout)

// ======================= FUNCTION DECLARATIONS =======================
bool takeSingleReading(float &distance, int &strength);
float takeBurstAverage(unsigned long &burstTime);
float filterAndAverage(float readings[], int count);
void calibrateBaseline();
float calculateSpeed(float startDist, float endDist, float timeSeconds);
bool isValidReading(float reading, int strength);
bool isTriggered(float reading);
bool isBaselineRestored(float reading);
bool isBaselineOpen();

// ======================= SETUP =======================
void setup() {
    Serial.begin(115200);
    Wire.begin();

    Serial.println(F("==================================="));
    Serial.println(F("DIY LIDAR SPEED CAMERA v2.0"));
    Serial.println(F("Burst-Gap-Burst Algorithm (Fixed)"));
    Serial.println(F("==================================="));
    Serial.println();

    if (DEBUG_MODE) {
        Serial.println(F("[DEBUG MODE ENABLED]"));
        Serial.println();
    }

    // Wait for TF-Luna to initialize
    delay(500);

    // Calibrate baseline distance
    calibrateBaseline();

    Serial.println();
    Serial.println(F("Speed camera ready. Monitoring for vehicles..."));
    Serial.println();
}

// ======================= MAIN LOOP =======================
void loop() {
    // Take a single reading to check current state
    float currentReading;
    int currentStrength;

    if (!takeSingleReading(currentReading, currentStrength)) {
        delay(10);
        return;  // Failed to get reading
    }

    // If detection is locked, check for timeout or baseline restoration
    if (detectionLocked) {
        unsigned long lockDuration = millis() - lockStartTime;

        // Check timeout
        if (lockDuration > DETECTION_TIMEOUT_MS) {
            if (DEBUG_MODE) {
                Serial.print(F(">> TIMEOUT: Lock released after "));
                Serial.print(lockDuration);
                Serial.println(F("ms"));
            }
            detectionLocked = false;
            Serial.println(F(">> Lock timeout. Ready for next vehicle."));
            Serial.println();
        }
        // Check baseline restoration
        else if (isBaselineRestored(currentReading)) {
            if (DEBUG_MODE) {
                Serial.print(F(">> Baseline restored after "));
                Serial.print(lockDuration);
                Serial.println(F("ms"));
            }
            detectionLocked = false;
            Serial.println(F(">> Baseline restored. Ready for next vehicle."));
            Serial.println();
        }

        delay(10);
        return;
    }

    // Check if we have a valid reading and if it's different from baseline (vehicle detected)
    if (isValidReading(currentReading, currentStrength) && isTriggered(currentReading)) {

        Serial.println(F(">> Vehicle detected! Starting speed measurement..."));
        if (DEBUG_MODE) {
            Serial.print(F("   Trigger: "));
            Serial.print(currentReading, 3);
            Serial.print(F("m, strength: "));
            Serial.println(currentStrength);
        }

        // ========== BURST 1 ==========
        unsigned long burst1Time;
        float burst1Average = takeBurstAverage(burst1Time);

        if (burst1Average < 0) {
            Serial.println(F("   Burst 1 failed - invalid readings. Resetting..."));
            delay(100);
            return;
        }

        Serial.print(F("   Burst 1 average: "));
        Serial.print(burst1Average, 3);
        Serial.println(F(" m"));

        // ========== GAP ==========
        unsigned long gapStart = micros();
        delay((unsigned long)GAP_TIME_MS);
        unsigned long gapEnd = micros();

        // ========== BURST 2 ==========
        unsigned long burst2Time;
        float burst2Average = takeBurstAverage(burst2Time);

        if (burst2Average < 0) {
            Serial.println(F("   Burst 2 failed - invalid readings. Resetting..."));
            delay(100);
            return;
        }

        Serial.print(F("   Burst 2 average: "));
        Serial.print(burst2Average, 3);
        Serial.println(F(" m"));

        // ========== CALCULATE ACTUAL TIME ELAPSED ==========
        // Time from middle of burst 1 to middle of burst 2
        unsigned long totalTime = (gapEnd - gapStart) + (burst1Time + burst2Time) / 2;
        float totalTimeSeconds = totalTime / 1000000.0;  // Convert microseconds to seconds

        if (DEBUG_MODE) {
            Serial.print(F("   Measurement time: "));
            Serial.print(totalTimeSeconds * 1000, 1);
            Serial.println(F(" ms"));
        }

        // ========== CALCULATE SPEED ==========
        float distanceChange = burst1Average - burst2Average;
        float absDistanceChange = abs(distanceChange);

        if (DEBUG_MODE) {
            Serial.print(F("   Distance change: "));
            Serial.print(absDistanceChange * 100, 1);
            Serial.println(F(" cm"));
        }

        // Validate distance change magnitude
        if (absDistanceChange < MIN_DISTANCE_CHANGE_M) {
            Serial.print(F("   >> Distance change too small ("));
            Serial.print(absDistanceChange * 100, 1);
            Serial.println(F("cm) - likely noise"));
            delay(100);
            return;
        }

        if (absDistanceChange > MAX_DISTANCE_CHANGE_M) {
            Serial.print(F("   >> Distance change too large ("));
            Serial.print(absDistanceChange, 2);
            Serial.println(F("m) - likely error"));
            delay(100);
            return;
        }

        float speed = calculateSpeed(burst1Average, burst2Average, totalTimeSeconds);
        float speedKmh = speed * 3.6;

        // Validate speed range
        if (speedKmh < MIN_SPEED_KMH) {
            Serial.print(F("   >> Speed too low ("));
            Serial.print(speedKmh, 1);
            Serial.println(F(" km/h) - ignoring"));
            delay(100);
            return;
        }

        if (speedKmh > MAX_SPEED_KMH) {
            Serial.print(F("   >> Speed too high ("));
            Serial.print(speedKmh, 1);
            Serial.println(F(" km/h) - likely error"));
            delay(100);
            return;
        }

        // ========== VALID SPEED DETECTED ==========
        Serial.println();
        Serial.println(F("========== SPEED RESULT =========="));
        Serial.print(F("   Distance change: "));
        Serial.print(absDistanceChange * 100, 1);
        Serial.println(F(" cm"));
        Serial.print(F("   Measurement time: "));
        Serial.print(totalTimeSeconds * 1000, 1);
        Serial.println(F(" ms"));
        Serial.print(F("   Raw speed: "));
        Serial.print(speed, 2);
        Serial.println(F(" m/s"));
        Serial.println();
        Serial.print(F("   >>> VEHICLE SPEED: "));
        Serial.print(speedKmh, 1);
        Serial.println(F(" km/h <<<"));
        Serial.println(F("=================================="));
        Serial.println();

        // Lock detection until baseline is restored (vehicle has passed)
        detectionLocked = true;
        lockStartTime = millis();
        Serial.println(F(">> Detection locked. Waiting for vehicle to pass..."));
        if (DEBUG_MODE) {
            Serial.print(F("   Timeout in "));
            Serial.print(DETECTION_TIMEOUT_MS / 1000);
            Serial.println(F(" seconds"));
        }
    }

    // Small delay between monitoring readings
    delay(10);
}

// ======================= HELPER FUNCTIONS =======================

/**
 * Take a single distance reading from the TF-Luna
 * Returns true if successful, false otherwise
 * Outputs distance in meters and signal strength
 */
bool takeSingleReading(float &distance, int &strength) {
    if (tflI2C.getData(tfDist, tfFlux, tfTemp, tfAddr)) {
        // TF-Luna outputs distance in centimeters, convert to meters
        distance = tfDist / 100.0;
        strength = tfFlux;
        return true;
    }
    return false;
}

/**
 * Check if a reading is valid (positive distance and good signal strength)
 */
bool isValidReading(float reading, int strength) {
    if (reading <= 0) return false;
    if (strength < MIN_SIGNAL_STRENGTH) {
        if (DEBUG_MODE) {
            Serial.print(F("   Low signal: "));
            Serial.print(strength);
            Serial.print(F(" (min: "));
            Serial.print(MIN_SIGNAL_STRENGTH);
            Serial.println(F(")"));
        }
        return false;
    }
    return true;
}

/**
 * Check if baseline is effectively "no wall" (0 or very large)
 */
bool isBaselineOpen() {
    return (baselineDistance <= 0 || baselineDistance > 7.5);  // TF-Luna max range ~8m
}

/**
 * Check if a reading indicates a vehicle has entered the detection zone
 * Triggered when reading is significantly different from baseline
 */
bool isTriggered(float reading) {
    // If baseline is 0 or beyond range, any valid reading is a trigger
    if (isBaselineOpen()) {
        return (reading > 0.2 && reading < 8.0);  // Valid TF-Luna range
    }

    // Otherwise, trigger if reading is significantly closer than baseline
    float differenceFromBaseline = baselineDistance - reading;
    return (differenceFromBaseline > (BASELINE_TOLERANCE_CM / 100.0));
}

/**
 * Check if the baseline has been restored (vehicle has passed)
 * Returns true when reading is back to baseline (or no object detected for open baseline)
 */
bool isBaselineRestored(float reading) {
    // If baseline is open (no wall), restored when reading is 0 or beyond range
    if (isBaselineOpen()) {
        return (reading <= 0 || reading > 7.5);  // No object in range
    }

    // Otherwise, restored when reading is close to the original baseline
    float differenceFromBaseline = abs(baselineDistance - reading);
    return (differenceFromBaseline <= (BASELINE_TOLERANCE_CM / 100.0));
}

/**
 * Take a burst of readings, filter outliers, and return the average
 * Also returns the time taken for the burst (in microseconds)
 * Returns -1 if not enough valid readings
 */
float takeBurstAverage(unsigned long &burstTime) {
    unsigned long startTime = micros();

    float readings[BURST_SIZE];
    int validCount = 0;

    // Take quick measurements
    for (int i = 0; i < BURST_SIZE; i++) {
        float reading;
        int strength;

        if (takeSingleReading(reading, strength) && isValidReading(reading, strength)) {
            readings[validCount] = reading;
            validCount++;
        }
        // Small delay between burst readings (TF-Luna can do up to 250Hz)
        delayMicroseconds(4000);  // ~4ms between readings for reliability
    }

    burstTime = micros() - startTime;

    if (validCount < 1) {
        if (DEBUG_MODE) {
            Serial.print(F("   Burst failed: only "));
            Serial.print(validCount);
            Serial.println(F(" valid readings"));
        }
        return -1.0;  // Not enough valid readings
    }

    if (DEBUG_MODE) {
        Serial.print(F("   Burst: "));
        Serial.print(validCount);
        Serial.print(F("/"));
        Serial.print(BURST_SIZE);
        Serial.println(F(" valid"));
    }

    return filterAndAverage(readings, validCount);
}

/**
 * Filter out outliers and return the average of remaining readings
 * Uses median-based outlier detection (more robust than voting)
 */
float filterAndAverage(float readings[], int count) {
    if (count == 0) return -1.0;
    if (count == 1) return readings[0];

    // Sort readings to find median
    for (int i = 0; i < count - 1; i++) {
        for (int j = 0; j < count - i - 1; j++) {
            if (readings[j] > readings[j + 1]) {
                float temp = readings[j];
                readings[j] = readings[j + 1];
                readings[j + 1] = temp;
            }
        }
    }

    // Use median for outlier detection
    float median = readings[count / 2];

    // Calculate MAD (Median Absolute Deviation)
    float mad = 0;
    for (int i = 0; i < count; i++) {
        float dev = abs(readings[i] - median);
        if (dev > mad) mad = dev;
    }

    // Remove outliers and calculate average
    float sum = 0;
    int validCount = 0;

    for (int i = 0; i < count; i++) {
        // Only remove if MAD is significant (> 2cm) and reading is far from median
        if (mad > 0.02 && abs(readings[i] - median) > 2.5 * mad) {
            if (DEBUG_MODE) {
                Serial.print(F("      Outlier: "));
                Serial.print(readings[i], 3);
                Serial.println(F("m"));
            }
            continue;  // Skip this outlier
        }
        sum += readings[i];
        validCount++;
    }

    if (validCount == 0) {
        if (DEBUG_MODE) {
            Serial.println(F("   All readings filtered!"));
        }
        return -1.0;
    }

    return sum / validCount;
}

/**
 * Calculate the speed of the vehicle
 *
 * Formula: speed = (startDist - endDist) / time / cos(angle)
 *
 * The cosine correction accounts for the 20° angle of the sensor
 */
float calculateSpeed(float startDist, float endDist, float timeSeconds) {
    // Distance change (positive if vehicle approaching)
    float distanceChange = startDist - endDist;

    // Raw speed along the sensor's line of sight
    float rawSpeed = distanceChange / timeSeconds;

    // Apply cosine correction for the 20° angle
    // This gives us the actual speed along the road
    float correctedSpeed = rawSpeed / COS_ANGLE;

    return correctedSpeed;  // Can be negative if vehicle receding
}

/**
 * Calibrate the baseline distance on startup
 * Takes multiple readings and averages them to establish the baseline
 */
void calibrateBaseline() {
    Serial.println(F("Calibrating baseline distance..."));
    Serial.println(F("(Make sure the road is clear of vehicles)"));

    float sum = 0;
    int validReadings = 0;
    const int CALIBRATION_SAMPLES = 10;

    for (int i = 0; i < CALIBRATION_SAMPLES; i++) {
        float reading;
        int strength;

        if (takeSingleReading(reading, strength) && reading > 0) {
            sum += reading;
            validReadings++;
            Serial.print(F("  Sample "));
            Serial.print(i + 1);
            Serial.print(F(": "));
            Serial.print(reading, 3);
            Serial.print(F(" m (strength: "));
            Serial.print(strength);
            Serial.println(F(")"));
        }
        delay(100);
    }

    if (validReadings > 0) {
        baselineDistance = sum / validReadings;
        baselineSet = true;

        Serial.println();
        Serial.print(F("Baseline distance set to: "));
        Serial.print(baselineDistance, 3);
        Serial.println(F(" m"));

        // If baseline is 0 or beyond TF-Luna range, note this
        if (isBaselineOpen()) {
            Serial.println(F("(No wall detected - baseline is open/infinite)"));
            baselineDistance = 0;  // Set to 0 for open baseline
        }
    } else {
        Serial.println(F("WARNING: Could not establish baseline!"));
        Serial.println(F("Proceeding with baseline = 0 (open)"));
        baselineDistance = 0;
        baselineSet = true;
    }
}
