/**
 * Team Settings Wrapper
 * Embeds TeamManagement component within settings layout
 */

import React from 'react';
import TeamManagement from '../TeamManagement';

const TeamSettings = () => {
    return <TeamManagement embedded={true} />;
};

export default TeamSettings;
