const { createRunOncePlugin, withAppBuildGradle } = require('@expo/config-plugins');
const packageJson = require('../package.json');

const GENERATED_TAG = 'agent-luotianyi-release-signing';

const gradleBlock = `// @generated begin ${GENERATED_TAG}
// Values come from Gradle properties or same-named environment variables.
def releaseSigningValue = { String name ->
    def gradleValue = findProperty(name)?.toString()?.trim()
    return gradleValue ?: System.getenv(name)?.trim()
}

def releaseSigningValues = [
    storeFile: releaseSigningValue("MYAPP_UPLOAD_STORE_FILE"),
    keyAlias: releaseSigningValue("MYAPP_UPLOAD_KEY_ALIAS"),
    storePassword: releaseSigningValue("MYAPP_UPLOAD_STORE_PASSWORD"),
    keyPassword: releaseSigningValue("MYAPP_UPLOAD_KEY_PASSWORD"),
]
def releaseSigningReady = releaseSigningValues.values().every { it != null && !it.isEmpty() }

android {
    signingConfigs {
        release {
            if (releaseSigningReady) {
                storeFile file(releaseSigningValues.storeFile)
                keyAlias releaseSigningValues.keyAlias
                storePassword releaseSigningValues.storePassword
                keyPassword releaseSigningValues.keyPassword
            }
        }
    }
    buildTypes {
        release {
            // Never silently publish a release variant with Expo's debug signing key.
            signingConfig = releaseSigningReady ? signingConfigs.release : null
        }
    }
}

def validateReleaseSigning = tasks.register("validateReleaseSigning") {
    doLast {
        if (!releaseSigningReady) {
            throw new GradleException("Missing release signing values. Set MYAPP_UPLOAD_STORE_FILE, MYAPP_UPLOAD_KEY_ALIAS, MYAPP_UPLOAD_STORE_PASSWORD and MYAPP_UPLOAD_KEY_PASSWORD.")
        }
        if (!file(releaseSigningValues.storeFile).isFile()) {
            throw new GradleException("Release keystore does not exist: " + releaseSigningValues.storeFile)
        }
    }
}

tasks.configureEach { task ->
    if (task.name == "packageRelease" || task.name == "bundleRelease") {
        task.dependsOn(validateReleaseSigning)
    }
}
// @generated end ${GENERATED_TAG}`;

function withAndroidReleaseSigning(config) {
  return withAppBuildGradle(config, (modConfig) => {
    if (modConfig.modResults.language !== 'groovy') {
      throw new Error('withAndroidReleaseSigning only supports Groovy app/build.gradle files');
    }

    const generatedBlockPattern = new RegExp(
      `\\n?// @generated begin ${GENERATED_TAG}[\\s\\S]*?// @generated end ${GENERATED_TAG}\\n?`,
      'g',
    );
    const withoutOldBlock = modConfig.modResults.contents.replace(generatedBlockPattern, '').trimEnd();
    modConfig.modResults.contents = `${withoutOldBlock}\n\n${gradleBlock}\n`;
    return modConfig;
  });
}

module.exports = createRunOncePlugin(
  withAndroidReleaseSigning,
  'with-android-release-signing',
  packageJson.version,
);
