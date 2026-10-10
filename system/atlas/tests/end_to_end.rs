// SPDX-License-Identifier: MulanPSL-2.0
use robonix_atlas::{
    client::AtlasClient,
    pb::{Kind, Transport, atlas_server::AtlasServer},
    service::{AtlasRegistry, AtlasService},
};
use std::sync::{
    Arc,
    atomic::{AtomicUsize, Ordering},
};
use std::time::Duration;

#[tokio::test]
async fn provider_queries_retry_transient_failures_with_a_bound() {
    for (code, failures, expected_attempts, succeeds) in [
        (tonic::Code::Unavailable, 1, 2, true),
        (tonic::Code::DeadlineExceeded, 1, 2, true),
        (tonic::Code::Unavailable, 10, 3, false),
        (tonic::Code::PermissionDenied, 1, 1, false),
    ] {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        drop(listener);
        let attempts = Arc::new(AtomicUsize::new(0));
        let intercepted = attempts.clone();
        let service = AtlasService::new(Arc::new(AtlasRegistry::default()));
        let server = tokio::spawn(async move {
            tonic::transport::Server::builder()
                .add_service(AtlasServer::with_interceptor(service, move |request| {
                    if intercepted.fetch_add(1, Ordering::SeqCst) < failures {
                        Err(tonic::Status::new(code, "injected query failure"))
                    } else {
                        Ok(request)
                    }
                }))
                .serve(address)
                .await
                .unwrap();
        });
        let mut client =
            AtlasClient::connect_with_retry(address.to_string(), 10, Duration::from_millis(20))
                .await
                .unwrap();
        let result = client
            .query(Kind::Unspecified, "", "", "", Transport::Unspecified)
            .await;
        assert_eq!(result.is_ok(), succeeds);
        assert_eq!(attempts.load(Ordering::SeqCst), expected_attempts);
        if let Ok(providers) = result {
            assert!(providers.is_empty());
        }
        server.abort();
        let _ = server.await;
    }
}
