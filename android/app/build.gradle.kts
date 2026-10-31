plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}
android {
    namespace = "com.obrmath.monitor"
    compileSdk = 35
    defaultConfig {
        applicationId = "com.obrmath.monitor"
        minSdk = 26
        targetSdk = 35
        versionCode = 8
        versionName = "0.6.0"
    }
    buildFeatures { compose = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    signingConfigs {
        create("operatorRelease") {
            val signingPath=System.getenv("OBR_SIGNING_STORE")
            if(signingPath!=null) {
                storeFile=file(signingPath)
                storePassword=System.getenv("OBR_SIGNING_PASSWORD")
                keyAlias="obr-math-release"
                keyPassword=System.getenv("OBR_SIGNING_PASSWORD")
            }
        }
    }
    buildTypes {
        getByName("release") {
            isDebuggable=false
            signingConfig=signingConfigs.getByName("operatorRelease")
        }
    }
}
dependencies {
    implementation(platform("androidx.compose:compose-bom:2025.03.00"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.work:work-runtime-ktx:2.10.1")
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
