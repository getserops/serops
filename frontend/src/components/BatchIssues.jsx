import React, { useState, useEffect } from "react";
import { Table, Pagination } from "react-bootstrap";
import { FaExclamationCircle } from "react-icons/fa";
import { useNavigate, useParams } from "react-router-dom";
import DataService from "../services/data.service";

const BatchIssues = () => {
  const { batchId } = useParams();
  const [currentPage, setCurrentPage] = useState(1);
  const [issuesData, setIssuesData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedIssue, setExpandedIssue] = useState(null);
  const navigate = useNavigate();
  const pageSize = 5;

  useEffect(() => {
    const fetchIssues = async () => {
      setLoading(true);
      setError(null);
      try {
        const issues = await DataService.getIssuesByBatch(batchId);

        if (!Array.isArray(issues)) {
          if (issues?.error?.includes("parsing analysis_text")) {
            const newError = {
              message: "Invalid JSON format in batch analysis",
              batch: issues.batchId || "Unknown batch",
              solution: "Check Elasticsearch index mapping and data format",
            };
            setIssuesData([newError]);
          } else {
            console.error("Issues is not an array:", issues);
            setError("Failed to load issues data");
            setIssuesData([]);
          }
          return;
        }
        setIssuesData(issues);
      } catch (error) {
        console.error("Failed to fetch issues:", error);
        setError(error.message || "An error occurred while fetching issues");
        setIssuesData([]);
      } finally {
        setLoading(false);
      }
    };

    fetchIssues();
  }, [batchId]);

  const getSeverityColor = (severity) => {
    switch (severity?.toLowerCase()) {
      case "critical":
        return "#e53935";
      case "warning":
        return "#fb8c00";
      case "medium":
        return "#fdd835";
      case "low":
        return "#43a047";
      case "info":
        return "#1e88e5";
      default:
        return "#6c757d";
    }
  };

  const toggleExpandIssue = (issueId) => {
    setExpandedIssue(expandedIssue === issueId ? null : issueId);
  };

  const handleSolutionClick = (issue, e) => {
    e.stopPropagation();
    navigate("/dash/chat", {
      state: {
        issueContext: {
          batchId: issue.batch,
          message: issue.message,
          solution: issue.solution,
          root_cause: issue.root_cause,
        },
      },
    });
  };

  if (loading) {
    return <div className="text-center">Loading issues..</div>;
  }

  if (error) {
    return (
      <div className="p-3 d-flex justify-content-center">
        <div
          className="bg-white p-3 rounded-3"
          style={{ maxWidth: "1400px", width: "100%" }}
        >
          <div className="alert alert-danger" role="alert">
            {error}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className="p-3 d-flex justify-content-center"
      style={{ marginLeft: "18%", marginRight: "2%", marginTop: "30px" }}
    >
      <div
        className="bg-white p-3 rounded-3"
        style={{ maxWidth: "1400px", width: "100%" }}
      >
        <div className="d-flex justify-content-between align-items-center mb-3">
          <h4 className="text-start mb-0">
            Issues for Batch {batchId} ({issuesData.length})
          </h4>
          <button
            className="btn btn-outline-primary btn-sm"
            onClick={() => navigate("/dash/issues")}
          >
            View All Issues
          </button>
        </div>

        {issuesData.length === 0 ? (
          <p>No issues found for batch {batchId}.</p>
        ) : (
          <>
            <Table
              bordered
              hover
              responsive
              className="rounded-4 overflow-hidden text-center"
              style={{ tableLayout: "auto" }}
            >
              <thead className="table-primary">
                <tr>
                  <th style={{ fontSize: "14px", width: "50%" }}>ERRORS</th>
                  <th style={{ fontSize: "14px", width: "15%" }}>BATCH ID</th>
                  <th style={{ fontSize: "14px", width: "15%" }}>SEVERITY</th>
                  <th
                    style={{ fontSize: "14px", width: "20%" }}
                    className="text-primary"
                  >
                    SOLUTION APPLIED
                  </th>
                </tr>
              </thead>
              <tbody>
                {issuesData
                  .slice((currentPage - 1) * pageSize, currentPage * pageSize)
                  .map((issue) => (
                    <React.Fragment key={issue.id}>
                      <tr 
                        onClick={() => toggleExpandIssue(issue.id)}
                        style={{ cursor: 'pointer' }}
                      >
                        <td
                          style={{ padding: "0.75rem", fontSize: "14px" }}
                          className="text-start"
                        >
                          <FaExclamationCircle
                            className="me-2"
                            style={{
                              color: getSeverityColor(
                                issue.message.match(/^\[([^\]]+)\]/)?.[1]
                              ),
                            }}
                          />
                          {issue.message.replace(/^\[[^\]]+\]\s*/, "")}
                        </td>
                        <td style={{ padding: "0.75rem", fontSize: "14px" }}>
                          {issue.batch}
                        </td>
                        <td style={{ padding: "0.75rem", fontSize: "14px" }}>
                          {issue.message.match(/^\[([^\]]+)\]/)?.[1] || "N/A"}
                        </td>
                        <td
                          style={{
                            padding: "0.75rem",
                            fontSize: "14px",
                            cursor: "pointer",
                          }}
                          className="text-primary text-decoration-none"
                          onClick={(e) => handleSolutionClick(issue, e)}
                        >
                          Solution
                        </td>
                      </tr>
                      {expandedIssue === issue.id && (
                        <tr>
                          <td colSpan="4" className="text-start bg-light">
                            <div style={{ padding: "1rem", fontSize: "14px" }}>
                              <strong>Root Cause :</strong> {issue.root_cause || "No root cause available"}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
              </tbody>
            </Table>

            <div className="d-flex justify-content-between align-items-center mt-3">
              <div style={{ width: "120px" }}></div>

              <Pagination className="mb-0">
                <Pagination.Prev
                  onClick={() => setCurrentPage(currentPage - 1)}
                  disabled={currentPage === 1}
                />

                {[...Array(Math.ceil(issuesData.length / pageSize))].map(
                  (_, index) => {
                    const pageNumber = index + 1;

                    if (
                      pageNumber === 1 ||
                      pageNumber === Math.ceil(issuesData.length / pageSize) ||
                      (pageNumber >= currentPage - 1 &&
                        pageNumber <= currentPage + 1)
                    ) {
                      return (
                        <Pagination.Item
                          key={pageNumber}
                          active={currentPage === pageNumber}
                          onClick={() => setCurrentPage(pageNumber)}
                        >
                          {pageNumber}
                        </Pagination.Item>
                      );
                    }

                    if (
                      (pageNumber === 2 && currentPage > 3) ||
                      (pageNumber ===
                        Math.ceil(issuesData.length / pageSize) - 1 &&
                        currentPage <
                          Math.ceil(issuesData.length / pageSize) - 2)
                    ) {
                      return <Pagination.Ellipsis key={pageNumber} />;
                    }

                    return null;
                  }
                )}

                <Pagination.Next
                  onClick={() => setCurrentPage(currentPage + 1)}
                  disabled={
                    currentPage === Math.ceil(issuesData.length / pageSize)
                  }
                />
              </Pagination>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default BatchIssues;