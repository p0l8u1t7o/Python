import {readFile,writeFile} from 'node:fs/promises';
const projects=['AutomaticAcid-BaseTitration','MilitaryGradePC','PCB-CopperAssembly','RobotArmPressSSD','shutter assembly'];
const source=await readFile(new URL('./cable-routing.js',import.meta.url));
for(const project of projects)await writeFile(new URL('../'+project+'/web/js/cable-routing.js',import.meta.url),source);
console.log('Updated cable-routing.js in all five standalone websites.');
