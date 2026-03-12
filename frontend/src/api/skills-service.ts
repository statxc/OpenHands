import { openHands } from "./open-hands-axios";
import { SkillInfo } from "#/types/settings";

interface SkillListResponse {
  skills: SkillInfo[];
}

class SkillsService {
  /**
   * Get the list of available skills (global + user skills)
   */
  static async getSkills(): Promise<SkillInfo[]> {
    const { data } = await openHands.get<SkillListResponse>("/api/v1/skills");
    return data.skills;
  }
}

export default SkillsService;
