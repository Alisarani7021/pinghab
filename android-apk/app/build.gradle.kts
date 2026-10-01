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
        versionCode = 7
        versionName = "2.7"
    }

    // اپ وب بدون کپی‌شدن، مستقیم از پوشه‌ی web داخل assets قرار می‌گیرد
    sourceSets["main"].assets.srcDirs("src/main/assets", "../../web")

    // پایگاه‌های دادهٔ واقعی (ip2asn / DB-IP / SecLists / فونت) فشرده‌نشده بسته‌بندی می‌شوند:
    // همان بایت‌های منتشرشدهٔ منبع، بدون دست‌کاری — و بارگذاری سریع‌تر روی گوشی.
    androidResources {
        noCompress += listOf("gz", "tsv", "csv", "txt", "woff2", "mmdb")
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
