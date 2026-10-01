plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "ir.dnsradar.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "ir.dnsradar.app"
        minSdk = 21
        targetSdk = 34
        versionCode = 8
        versionName = "2.8"
    }

    // اپ وب بدون کپی‌شدن، مستقیم از پوشه‌ی web داخل assets قرار می‌گیرد
    sourceSets["main"].assets.srcDirs("src/main/assets", "../../web")

    // فونت (woff2) خودش فشرده است و دوباره فشرده نمی‌شود؛ بقیهٔ داده‌ها با deflate بسته‌بندی می‌شوند
    // تا حجم دانلود معقول بماند (همان بایت‌های منبع، فقط فشرده‌سازیِ بسته).
    androidResources {
        noCompress += listOf("woff2")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.webkit:webkit:1.11.0")
    implementation("androidx.core:core-ktx:1.13.1")
}
