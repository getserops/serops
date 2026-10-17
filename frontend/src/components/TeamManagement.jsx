
import React, { useState, useEffect } from 'react';
import { Container, Row, Col, Table, Button, Modal, Form, Badge, Spinner } from 'react-bootstrap';
import { toast } from 'react-toastify';
import { useTranslation } from 'react-i18next';
import { FaUserPlus, FaEdit, FaTrash, FaEnvelope, FaUsers, FaUserShield, FaUserFriends, FaUserCog } from 'react-icons/fa';
import { OrganisationService } from '../services/organisation.service';
import { canManageUsers, getRoleDisplayName, getRoleColor } from '../utils/permissions';
import CollapsibleSection from './settings/CollapsibleSection';
import './settings/SettingsLayout.css';

const TeamManagement = ({ embedded = false }) => {
    const { t } = useTranslation();
    // Get user from localStorage (same pattern as other components)
    const user = JSON.parse(localStorage.getItem("user")) || {};
    const [teamMembers, setTeamMembers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showModal, setShowModal] = useState(false);
    const [modalMode, setModalMode] = useState('add'); // 'add' or 'edit'
    const [selectedMember, setSelectedMember] = useState(null);
    const [formData, setFormData] = useState({
        email: '',
        role: 'user'  // Default role for new invites
    });

    useEffect(() => {
        fetchTeamMembers();
    }, []);

    const fetchTeamMembers = async () => {
        try {
            setLoading(true);
            const response = await OrganisationService.getTeamMembers();
            setTeamMembers(response.users || []);
        } catch (error) {
            toast.error(t('team.loadFailed'));
            console.error('Error fetching team:', error);
        } finally {
            setLoading(false);
        }
    };

    const handleOpenModal = (mode, member = null) => {
        setModalMode(mode);
        if (mode === 'edit' && member) {
            setSelectedMember(member);
            setFormData({
                email: member.email || '',
                first_name: member.first_name || '',
                last_name: member.last_name || '',
                phone: member.phone || '',
                role: member.role || 'user'
            });
        } else {
            setSelectedMember(null);
            setFormData({
                email: '',
                role: 'user'  // Default role for new invites
            });
        }
        setShowModal(true);
    };

    const handleCloseModal = () => {
        setShowModal(false);
        setSelectedMember(null);
        setFormData({
            email: '',
            role: 'user'
        });
    };

    const handleInputChange = (e) => {
        const { name, value } = e.target;
        setFormData(prev => ({ ...prev, [name]: value }));
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!formData.email) {
            toast.error(t('team.fillRequired'));
            return;
        }

        try {
            if (modalMode === 'add') {
                await OrganisationService.inviteTeamMember({ user: formData });
                toast.success(t('team.invitationSent'));
            } else {
                await OrganisationService.updateTeamMember(selectedMember.id, formData);
                toast.success(t('team.memberUpdated'));
            }
            handleCloseModal();
            fetchTeamMembers();
        } catch (error) {
            toast.error(error.response?.data?.error || t('team.operationFailed'));
        }
    };

    const handleDelete = async (memberId) => {
        if (!window.confirm(t('team.confirmRemove'))) {
            return;
        }

        try {
            await OrganisationService.deleteTeamMember(memberId);
            toast.success(t('team.memberRemoved'));
            fetchTeamMembers();
        } catch (error) {
            toast.error(t('team.removeFailed'));
        }
    };

    // Check if current user has permission to manage users
    if (!canManageUsers(user?.role)) {
        return (
            <div className="text-center p-5">
                <h4 className="text-muted">{t('team.accessDenied')}</h4>
                <p>{t('team.noPermission')}</p>
            </div>
        );
    }

    const content = (
        <div className="settings-section">
            <div className="settings-header">
                <div className="settings-icon-wrapper primary">
                    <FaUsers />
                </div>
                <div>
                    <h2>{t('team.title')}</h2>
                    <p>{t('team.subtitle')}</p>
                </div>
                <div className="ms-auto">
                    <button
                        className="btn btn-primary d-flex align-items-center gap-2"
                        onClick={() => handleOpenModal('add')}
                        style={{ borderRadius: '8px', padding: '0.6rem 1.2rem' }}
                    >
                        <FaUserPlus /> {t('team.inviteUser')}
                    </button>
                </div>
            </div>

            <CollapsibleSection
                title={t('team.membersList') || "Team Members"}
                description={t('team.membersDesc') || "Manage your team members and roles"}
                defaultExpanded={true}
            >
                <div className="settings-card-body p-0 overflow-hidden">
                    {loading ? (
                        <div className="text-center py-5">
                            <Spinner animation="border" variant="primary" />
                            <p className="mt-3 text-muted">{t('team.loading')}</p>
                        </div>
                    ) : teamMembers.length === 0 ? (
                        <div className="text-center py-5">
                            <div className="mb-3 text-muted opacity-25" style={{ fontSize: '3rem' }}>
                                <FaUserFriends />
                            </div>
                            <h4 className="text-muted">{t('team.noMembers')}</h4>
                            <p className="text-muted mb-4">{t('team.inviteFirst')}</p>
                            <Button variant="outline-primary" onClick={() => handleOpenModal('add')}>
                                <FaUserPlus className="me-2" /> {t('team.inviteMember')}
                            </Button>
                        </div>
                    ) : (
                        <Table hover responsive className="mb-0 align-middle table-stack">
                            <thead className="bg-light">
                                <tr>
                                    <th className="ps-4 py-3 border-0 text-uppercase small fw-bold text-muted">{t('team.userColumn')}</th>
                                    <th className="py-3 border-0 text-uppercase small fw-bold text-muted">{t('team.email')}</th>
                                    <th className="py-3 border-0 text-uppercase small fw-bold text-muted">{t('team.role')}</th>
                                    <th className="py-3 border-0 text-uppercase small fw-bold text-muted">{t('team.status')}</th>
                                    <th className="text-end pe-4 py-3 border-0 text-uppercase small fw-bold text-muted">{t('team.actions')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {teamMembers.map((member) => (
                                    <tr key={member.id}>
                                        <td className="ps-4">
                                            <div className="d-flex align-items-center">
                                                <div
                                                    className="rounded-circle bg-primary text-white d-flex align-items-center justify-content-center me-3"
                                                    style={{ width: 40, height: 40, fontSize: 16, fontWeight: 600 }}
                                                >
                                                    {member.first_name?.[0]}{member.last_name?.[0]}
                                                </div>
                                                <div>
                                                    <div className="fw-medium text-dark">{member.first_name} {member.last_name}</div>
                                                    <small className="text-muted">{member.phone || t('team.noPhone')}</small>
                                                </div>
                                            </div>
                                        </td>
                                        <td className="text-muted">{member.email}</td>
                                        <td>
                                            <Badge
                                                bg="light"
                                                text="dark"
                                                className="border fw-normal px-3 py-2"
                                                style={{
                                                    borderColor: getRoleColor(member.role),
                                                    color: getRoleColor(member.role)
                                                }}
                                            >
                                                {member.role === 'admin' && <FaUserShield className="me-1" />}
                                                {member.role === 'user' && <FaUserCog className="me-1" />}
                                                {member.role === 'viewer' && <FaUserFriends className="me-1" />}
                                                {getRoleDisplayName(member.role)}
                                            </Badge>
                                        </td>
                                        <td>
                                            <span className={`badge rounded-pill ${
                                                (member.status || (member.is_active && member.last_login ? 'active' : 'pending')) === 'active'
                                                    ? 'bg-success-subtle text-success-emphasis'
                                                    : (member.status === 'suspended' ? 'bg-secondary-subtle text-secondary-emphasis' : 'bg-warning-subtle text-warning-emphasis')
                                            } px-3 py-2`}>
                                                {(member.status || (member.is_active && member.last_login ? 'active' : 'pending')) === 'active'
                                                    ? t('team.active')
                                                    : member.status === 'suspended'
                                                        ? t('team.suspended', 'Suspended')
                                                        : t('team.pending')}
                                            </span>
                                        </td>
                                        <td className="text-end pe-4">
                                            {member.id !== user?.id && (
                                                <div className="d-flex justify-content-end gap-2">
                                                    <Button
                                                        variant="outline-primary"
                                                        size="sm"
                                                        onClick={() => handleOpenModal('edit', member)}
                                                        title={t('team.editUser')}
                                                    >
                                                        <FaEdit />
                                                    </Button>
                                                    <Button
                                                        variant="outline-danger"
                                                        size="sm"
                                                        onClick={() => handleDelete(member.id)}
                                                        title={t('team.removeUser')}
                                                    >
                                                        <FaTrash />
                                                    </Button>
                                                </div>
                                            )}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </Table>
                    )}
                </div>
            </CollapsibleSection>

            {/* Add/Edit Modal */}
            <Modal show={showModal} onHide={handleCloseModal} centered>
                <Modal.Header closeButton className="border-0 pb-0">
                    <Modal.Title className="fw-bold">
                        {modalMode === 'add' ? (
                            <>
                                <FaUserPlus className="me-2 text-primary" />
                                {t('team.inviteTeamMember')}
                            </>
                        ) : (
                            <>
                                <FaEdit className="me-2 text-primary" />
                                {t('team.editTeamMember')}
                            </>
                        )}
                    </Modal.Title>
                </Modal.Header>
                <Form onSubmit={handleSubmit}>
                    <Modal.Body className="pt-4">
                        <Form.Group className="mb-3">
                            <Form.Label className="fw-medium">{t('team.emailLabel')} <span className="text-danger">*</span></Form.Label>
                            <Form.Control
                                type="email"
                                name="email"
                                value={formData.email}
                                onChange={handleInputChange}
                                placeholder={t('team.emailPlaceholder')}
                                disabled={modalMode === 'edit'}
                                required
                                className="form-control-lg fs-6"
                            />
                            {modalMode === 'add' && (
                                <Form.Text className="text-muted">
                                    {t('team.invitationEmailHint')}
                                </Form.Text>
                            )}
                        </Form.Group>

                        {/* Name fields only for edit mode */}
                        {modalMode === 'edit' && (
                            <>
                                <Row>
                                    <Col md={6}>
                                        <Form.Group className="mb-3">
                                            <Form.Label className="fw-medium">{t('team.firstName')}</Form.Label>
                                            <Form.Control
                                                type="text"
                                                name="first_name"
                                                value={formData.first_name || ''}
                                                onChange={handleInputChange}
                                                placeholder={t('team.firstName')}
                                                className="form-control-lg fs-6"
                                            />
                                        </Form.Group>
                                    </Col>
                                    <Col md={6}>
                                        <Form.Group className="mb-3">
                                            <Form.Label className="fw-medium">{t('team.lastName')}</Form.Label>
                                            <Form.Control
                                                type="text"
                                                name="last_name"
                                                value={formData.last_name || ''}
                                                onChange={handleInputChange}
                                                placeholder={t('team.lastName')}
                                                className="form-control-lg fs-6"
                                            />
                                        </Form.Group>
                                    </Col>
                                </Row>

                                <Form.Group className="mb-3">
                                    <Form.Label className="fw-medium">{t('team.phone')}</Form.Label>
                                    <Form.Control
                                        type="tel"
                                        name="phone"
                                        value={formData.phone || ''}
                                        onChange={handleInputChange}
                                        placeholder={t('team.phonePlaceholder')}
                                        className="form-control-lg fs-6"
                                    />
                                </Form.Group>
                            </>
                        )}

                        <Form.Group className="mb-4">
                            <Form.Label className="fw-medium">{t('team.roleLabel')} <span className="text-danger">*</span></Form.Label>
                            <div className="d-flex flex-column gap-2">
                                <Form.Check
                                    type="radio"
                                    id="role-viewer"
                                    name="role"
                                    label={
                                        <div>
                                            <div className="fw-medium">{t('team.viewer') || 'Viewer'}</div>
                                            <div className="text-muted small">{t('team.viewerDesc') || 'Read-only access to dashboards, logs, and issues'}</div>
                                        </div>
                                    }
                                    checked={formData.role === 'viewer'}
                                    onChange={() => setFormData({ ...formData, role: 'viewer' })}
                                    className="p-3 border rounded"
                                />
                                <Form.Check
                                    type="radio"
                                    id="role-user"
                                    name="role"
                                    label={
                                        <div>
                                            <div className="fw-medium">{t('team.userRole') || 'User'}</div>
                                            <div className="text-muted small">{t('team.userDesc') || 'Can trigger analysis, use chat, and manage issues'}</div>
                                        </div>
                                    }
                                    checked={formData.role === 'user'}
                                    onChange={() => setFormData({ ...formData, role: 'user' })}
                                    className="p-3 border rounded"
                                />
                                <Form.Check
                                    type="radio"
                                    id="role-admin"
                                    name="role"
                                    label={
                                        <div>
                                            <div className="fw-medium text-danger">{t('team.admin')}</div>
                                            <div className="text-muted small">{t('team.adminDesc')}</div>
                                        </div>
                                    }
                                    checked={formData.role === 'admin'}
                                    onChange={() => setFormData({ ...formData, role: 'admin' })}
                                    className="p-3 border rounded"
                                />
                            </div>
                        </Form.Group>
                    </Modal.Body>
                    <Modal.Footer className="border-0 pt-0">
                        <Button variant="light" onClick={handleCloseModal}>
                            {t('common.cancel')}
                        </Button>
                        <Button variant="primary" type="submit" onClick={handleSubmit}>
                            {modalMode === 'add' ? (
                                <>
                                    <FaEnvelope className="me-2" />
                                    {t('team.sendInvitation')}
                                </>
                            ) : (
                                t('team.saveChanges')
                            )}
                        </Button>
                    </Modal.Footer>
                </Form>
            </Modal >
        </div>
    );

    // Return with or without Container wrapper based on embedded prop
    if (embedded) {
        return content;
    }

    return (
        <Container fluid className="py-4">
            {content}
        </Container>
    );
};

export default TeamManagement;
