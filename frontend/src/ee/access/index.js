import './i18n';
import RolesSettings from './RolesSettings';
import ProjectAccessPanel from './ProjectAccessPanel';

export default {
    settingsPages: [
        { path: 'roles', perm: 'team.manage', after: '/dash/settings/team', label: (t) => t('roles.title'), Component: RolesSettings },
    ],
    projectTabs: [
        {
            key: 'access',
            label: (t) => t('projectAccess.tab'),
            icon: 'lock',
            // Admins of this project who can manage teams.
            visible: ({ project, can, canOnProject }) => !!project && canOnProject(project, 'project.delete') && can('team.manage'),
            Component: ProjectAccessPanel,
        },
    ],
};
