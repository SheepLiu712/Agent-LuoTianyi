const { createRunOncePlugin, withAppBuildGradle } = require('@expo/config-plugins');
const packageJson = require('../package.json');

const GENERATED_TAG = 'agent-luotianyi-live2d-assets';

const gradleBlock = `// @generated begin ${GENERATED_TAG}
// Keep WebView's file:///android_asset/public/... tree synchronized at every Android build.
def live2dPublicSourceDir = new File(rootProject.projectDir.parentFile, "public")
def live2dGeneratedAssetsDir = new File(buildDir, "generated/live2dAssets")

tasks.register("syncLive2DPublicAssets", Sync) {
    from(live2dPublicSourceDir)
    into(new File(live2dGeneratedAssetsDir, "public"))
}

android.sourceSets.main.assets.srcDir(live2dGeneratedAssetsDir)
tasks.named("preBuild").configure {
    dependsOn("syncLive2DPublicAssets")
}
// @generated end ${GENERATED_TAG}`;

function withLive2DAndroidAssets(config) {
  return withAppBuildGradle(config, (modConfig) => {
    if (modConfig.modResults.language !== 'groovy') {
      throw new Error('withLive2DAndroidAssets only supports Groovy app/build.gradle files');
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
  withLive2DAndroidAssets,
  'with-live2d-android-assets',
  packageJson.version,
);
