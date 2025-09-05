const fs = require('fs');
const { execSync } = require('child_process');
const path = require('path');

exports.default = async function(context) {
  const artifactPaths = context.artifactPaths || [];
  for (const artifact of artifactPaths) {
    if (artifact.endsWith('.dmg')) {
      const dmgPath = path.resolve(artifact);
      const zipPath = dmgPath.replace(/\\.dmg$/, '.zip');
      console.log(`[zip-dmg] Zipping ${dmgPath} → ${zipPath}`);
      execSync(`zip -j "${zipPath}" "${dmgPath}"`, { stdio: 'inherit' });
    }
  }
};
